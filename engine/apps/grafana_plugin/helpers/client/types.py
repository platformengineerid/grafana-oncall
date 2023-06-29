import typing

import requests

from apps.api.permissions import GrafanaAPIPermission


class GrafanaUser(typing.TypedDict):
    orgId: int
    userId: int
    email: str
    name: str
    avatarUrl: str
    login: str
    role: str
    lastSeenAt: str
    lastSeenAtAge: str


class GrafanaUserWithPermissions(GrafanaUser):
    permissions: typing.List[GrafanaAPIPermission]


GrafanaUsersWithPermissions = typing.List[GrafanaUserWithPermissions]
UserPermissionsDict = typing.Dict[str, typing.List[GrafanaAPIPermission]]


class GCOMInstanceInfoConfigFeatureToggles(typing.TypedDict):
    accessControlOnCall: str


class GCOMInstanceInfoConfig(typing.TypedDict):
    feature_toggles: GCOMInstanceInfoConfigFeatureToggles


class GCOMInstanceInfo(typing.TypedDict):
    id: int
    orgId: int
    slug: str
    orgSlug: str
    orgName: str
    url: str
    status: str
    clusterSlug: str
    config: GCOMInstanceInfoConfig | None


class ApiClientResponseCallStatus(typing.TypedDict):
    url: str
    connected: bool
    status_code: int
    message: str


# TODO: come back and make the typing.Dict strongly typed once we switch to Python 3.12
# which has better support for generics
_APIClientResponse = typing.Optional[typing.Dict | typing.List]
APIClientResponse = typing.Tuple[_APIClientResponse, ApiClientResponseCallStatus]


# can't define this using class syntax because one of the keys contains a dash
# https://docs.python.org/3/library/typing.html#typing.TypedDict:~:text=The%20functional%20syntax%20should%20also%20be%20used%20when%20any%20of%20the%20keys%20are%20not%20valid%20identifiers%2C%20for%20example%20because%20they%20are%20keywords%20or%20contain%20hyphens.%20Example%3A
APIRequestHeaders = typing.TypedDict(
    "APIRequestHeaders",
    {
        "User-Agent": str,
        "Authorization": str,
    },
)


class HttpMethod(typing.Protocol):
    """
    TODO: can probably replace this with something from the requests library?
    https://github.com/psf/requests/blob/main/requests/api.py#L14
    """

    @property
    def __name__(self) -> str:
        ...

    def __call__(self, *args, **kwargs) -> requests.Response:
        ...
