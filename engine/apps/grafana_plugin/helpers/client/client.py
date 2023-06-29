import json
import logging
import time
import typing
from urllib.parse import urljoin

import requests
from django.conf import settings
from rest_framework import status

from apps.api.permissions import ACTION_PREFIX, GrafanaAPIPermission
from apps.grafana_plugin.helpers.client import exceptions, types

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, api_url: str, api_token: str) -> None:
        self.api_url = api_url
        self.api_token = api_token

    def api_head(self, endpoint: str, body: typing.Optional[typing.Dict] = None, **kwargs) -> types.APIClientResponse:
        return self.call_api(endpoint, requests.head, body, **kwargs)

    def api_get(self, endpoint: str, **kwargs) -> types.APIClientResponse:
        return self.call_api(endpoint, requests.get, **kwargs)

    def api_post(self, endpoint: str, body: typing.Optional[typing.Dict] = None, **kwargs) -> types.APIClientResponse:
        return self.call_api(endpoint, requests.post, body, **kwargs)

    def call_api(
        self, endpoint: str, http_method: types.HttpMethod, body: typing.Optional[typing.Dict] = None, **kwargs
    ) -> types.APIClientResponse:
        request_start = time.perf_counter()
        call_status: types.ApiClientResponseCallStatus = {
            "url": urljoin(self.api_url, endpoint),
            "connected": False,
            "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            "message": "",
        }
        try:
            response = http_method(call_status["url"], json=body, headers=self.request_headers, **kwargs)
            call_status["status_code"] = response.status_code
            response.raise_for_status()

            call_status["connected"] = True
            call_status["message"] = response.reason

            if response.status_code == status.HTTP_204_NO_CONTENT:
                return {}, call_status

            # ex. a HEAD call (self.api_head) would have a response.content of b''
            # and hence calling response.json() throws a json.JSONDecodeError
            return response.json() if response.content else None, call_status
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
            requests.exceptions.TooManyRedirects,
            requests.exceptions.Timeout,
            json.JSONDecodeError,
        ) as e:
            logger.warning("Error connecting to api instance " + str(e))
            call_status["message"] = "{0}".format(e)
        finally:
            request_end = time.perf_counter()
            status_code = call_status["status_code"]
            url = call_status["url"]
            seconds = request_end - request_start
            logging.info(
                f"outbound latency={str(seconds)} status={status_code} "
                f"method={http_method.__name__.upper()} url={url} "
                f"slow={int(seconds > settings.SLOW_THRESHOLD_SECONDS)} "
            )
        return None, call_status

    @property
    def request_headers(self) -> types.APIRequestHeaders:
        return {"User-Agent": settings.GRAFANA_COM_USER_AGENT, "Authorization": f"Bearer {self.api_token}"}


class GrafanaAPIClient(APIClient):
    USER_PERMISSION_ENDPOINT = f"api/access-control/users/permissions/search?actionPrefix={ACTION_PREFIX}"

    def __init__(self, api_url: str, api_token: str) -> None:
        super().__init__(api_url, api_token)

    def check_token(self) -> types.APIClientResponse:
        return self.api_head("api/org")

    def get_users_permissions(self, rbac_is_enabled_for_org: bool) -> types.UserPermissionsDict:
        """
        It is possible that this endpoint may not be available for certain Grafana orgs.
        Ex: for Grafana Cloud orgs whom have pinned their Grafana version to an earlier version
        where this endpoint is not available

        The response from the Grafana endpoint will look something like this:
        {
            "1": {
                "grafana-oncall-app.alert-groups:read": [
                    ""
                ],
                "grafana-oncall-app.alert-groups:write": [
                    ""
                ]
            }
        }
        """
        if not rbac_is_enabled_for_org:
            return {}
        response, _ = self.api_get(self.USER_PERMISSION_ENDPOINT)
        if response is None:
            return {}
        elif isinstance(response, list):
            return {}

        data: typing.Dict[str, typing.Dict[str, typing.List[str]]] = response

        all_users_permissions: types.UserPermissionsDict = {}
        for user_id, user_permissions in data.items():
            all_users_permissions[user_id] = [GrafanaAPIPermission(action=key) for key, _ in user_permissions.items()]

        return all_users_permissions

    def is_rbac_enabled_for_organization(self) -> bool:
        _, resp_status = self.api_head(self.USER_PERMISSION_ENDPOINT)
        return resp_status["connected"]

    def get_users(self, rbac_is_enabled_for_org: bool, **kwargs) -> types.GrafanaUsersWithPermissions:
        users_response, _ = self.api_get("api/org/users", **kwargs)

        if not users_response:
            return []
        elif isinstance(users_response, dict):
            return []

        users: types.GrafanaUsersWithPermissions = users_response

        user_permissions = self.get_users_permissions(rbac_is_enabled_for_org)

        # merge the users permissions response into the org users response
        for user in users:
            user["permissions"] = user_permissions.get(str(user["userId"]), [])
        return users

    def get_teams(self, **kwargs) -> types.APIClientResponse:
        return self.api_get("api/teams/search?perpage=1000000", **kwargs)

    def get_team_members(self, team_id: int) -> types.APIClientResponse:
        return self.api_get(f"api/teams/{team_id}/members")

    def get_datasources(self) -> types.APIClientResponse:
        return self.api_get("api/datasources")

    def get_datasource_by_id(self, datasource_id) -> types.APIClientResponse:
        # This endpoint is deprecated for Grafana version >= 9. Use get_datasource instead
        return self.api_get(f"api/datasources/{datasource_id}")

    def get_datasource(self, datasource_uid) -> types.APIClientResponse:
        return self.api_get(f"api/datasources/uid/{datasource_uid}")

    def get_alertmanager_status_with_config(self, recipient) -> types.APIClientResponse:
        return self.api_get(f"api/alertmanager/{recipient}/api/v2/status")

    def get_alerting_config(self, recipient: str) -> types.APIClientResponse:
        return self.api_get(f"api/alertmanager/{recipient}/config/api/v1/alerts")

    def update_alerting_config(self, recipient, config) -> types.APIClientResponse:
        return self.api_post(f"api/alertmanager/{recipient}/config/api/v1/alerts", config)

    def get_grafana_plugin_settings(self, recipient: str) -> types.APIClientResponse:
        return self.api_get(f"api/plugins/{recipient}/settings")


class GcomAPIClient(APIClient):
    ACTIVE_INSTANCE_QUERY = "instances?status=active"
    DELETED_INSTANCE_QUERY = "instances?status=deleted&includeDeleted=true"
    STACK_STATUS_DELETED = "deleted"
    STACK_STATUS_ACTIVE = "active"

    def __init__(self, api_token: str) -> None:
        super().__init__(settings.GRAFANA_COM_API_URL, api_token)

    def get_instance_info(
        self, stack_id: str, include_config_query_param: bool = False
    ) -> typing.Optional[types.GCOMInstanceInfo]:
        """
        NOTE: in order to use ?config=true, an "Admin" GCOM token must be used to make the API call
        """
        url = f"instances/{stack_id}"
        if include_config_query_param:
            url += "?config=true"

        data, _ = self.api_get(url)
        return data

    def _feature_toggle_is_enabled(self, instance_info: types.GCOMInstanceInfo, feature_name: str) -> bool:
        """
        there are two ways that feature toggles can be enabled, this method takes into account both
        https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/#enable
        """
        instance_info_config = instance_info.get("config", {})
        if not instance_info_config:
            return False

        instance_feature_toggles = instance_info_config.get("feature_toggles", {})

        if not instance_feature_toggles:
            return False

        # features enabled via enable key are space separated
        features_enabled_via_enable_key = instance_feature_toggles.get("enable", "").split(" ")
        feature_enabled_via_enable_key = feature_name in features_enabled_via_enable_key
        feature_enabled_via_direct_key = instance_feature_toggles.get(feature_name, "false") == "true"

        return feature_enabled_via_enable_key or feature_enabled_via_direct_key

    def is_rbac_enabled_for_stack(self, stack_id: str) -> bool:
        """
        NOTE: must use an "Admin" GCOM token when calling this method
        """
        instance_info = self.get_instance_info(stack_id, True)
        if not instance_info:
            return False
        return self._feature_toggle_is_enabled(instance_info, "accessControlOnCall")

    def get_instances(self, query: str):
        return self.api_get(query)

    def is_stack_deleted(self, stack_id: str) -> bool:
        url = f"instances?includeDeleted=true&id={stack_id}"
        instance_infos, _ = self.api_get(url)

        if not isinstance(instance_infos, dict):
            raise exceptions.UnexpectedResponseJSONPayloadType(
                f"Unexpected JSON payload type received. Expected dict, got {type(instance_infos)}"
            )

        return instance_infos["items"] and instance_infos["items"][0].get("status") == self.STACK_STATUS_DELETED

    def post_active_users(self, body) -> types.APIClientResponse:
        return self.api_post("app-active-users", body)

    def get_stack_regions(self) -> types.APIClientResponse:
        return self.api_get("stack-regions")
