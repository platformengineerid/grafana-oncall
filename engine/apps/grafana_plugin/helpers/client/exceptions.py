class UnexpectedResponseJSONPayloadType(Exception):
    """
    Raised when an unexpected HTTP response payload data type is returned.

    Ex. a list is returned as opposed to a dictionary (object)
    """
