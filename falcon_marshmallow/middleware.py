# -*- coding: utf-8 -*-
"""Middleware class(es) for Falcon-Marshmallow"""

# Std lib
from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)
import logging

from typing import Any, Iterable, Optional

# Third party
from falcon.vendor import mimeparse
import marshmallow
from marshmallow import Schema, ValidationError

import simplejson

from falcon import Request, Response
from falcon.errors import (
    HTTPBadRequest,
    HTTPInternalServerError,
    HTTPNotAcceptable,
    HTTPUnprocessableEntity,
    HTTPUnsupportedMediaType,
)


log = logging.getLogger(__name__)


JSON_CONTENT_REQUIRED_METHODS = ("POST", "PUT", "PATCH")
JSON_CONTENT_TYPE = "application/json"
CONTENT_KEY = "content"
MARSHMALLOW_2 = marshmallow.__version_info__ < (3,)


def get_stashed_content(req):
    # type: (Request) -> Any
    """Allow multiple middlewares acting on data in the request stream.

    For this to work, no middlewware should use `req.stream.read()` directly,
    as that will either cause this to get `EOF` (`b''`) or the middleware will
    get `EOF` if this runs first.

    The issue is that without more elaborate measures (which we could do at
    some point), the first middleware to use `req.stream.read()` will make
    an following middleware get no data, as the stream is not seekable; it does
    not support being rewound (no `seek(0)`).
    """
    # This is the key which will hold the already-read content.
    if req.context.get(CONTENT_KEY) is None:
        req.context[CONTENT_KEY] = req.bounded_stream.read()

    return req.context[CONTENT_KEY]


class JSONEnforcer:
    """Enforce that requests are JSON compatible"""

    def __init__(self, required_methods=JSON_CONTENT_REQUIRED_METHODS):
        # type: (Iterable[str]) -> None
        """Initialize the middleware

        :param required_methods: a collection of HTTP methods for
            which "application/json" should be required as a
            Content-Type header
        """
        log.debug("JSONEnforcer.__init__(%s)", required_methods)
        self._methods = tuple(required_methods)

    def process_request(self, req, resp):
        # type: (Request, Response) -> None
        """Ensure requests accept JSON or specify JSON as content type

        :param req: the passed request object
        :param resp: the passed repsonse object

        :raises HttpNotAcceptable: if the request does not specify
            "application/json" responses as acceptable
        :raises HttpUnsupportedContentType: if a request of a type
            specified by "required_methods" does not specify a
            content-type of "application/json"
        """
        log.debug("JSONEnforcer.process_request(%s, %s)", req, resp)
        if not req.client_accepts_json:
            raise HTTPNotAcceptable(
                description=(
                    "This server only supports responses encoded as JSON. "
                    'Please update your "Accept" header to include '
                    '"application/json".'
                )
            )

        if req.method in JSON_CONTENT_REQUIRED_METHODS:
            if (
                req.content_type is None
                or "application/json" not in req.content_type
            ):
                raise HTTPUnsupportedMediaType(
                    description=(
                        '%s requests must have "application/json" in their '
                        '"Content-Type" header.' % req.method
                    )
                )


class EmptyRequestDropper:
    """Check and drop empty requests"""

    def process_request(self, req, resp):
        # type: (Request, Response) -> None
        """Ensure that a request does not contain an empty body

        If a request has content length, but its body is empty,
        raise an HTTPBadRequest error.

        :param req: the passed request object
        :param resp: the passed response object

        :raises HTTPBadRequest: if the request has content length with
            an empty body
        """
        log.debug("EmptyRequestDropper.process_request(%s, %s)", req, resp)
        if req.content_length in (None, 0):
            return

        content = get_stashed_content(req)

        # If the content is _still_ Falsy (e.g., something empty like b'')
        if not content:
            raise HTTPBadRequest(
                description=(
                    "Empty response body. A valid JSON document is required."
                )
            )


class Marshmallow:
    """Attempt to deserialize objects with any available schemas"""

    # TODO: consider some sort of config object as the options here
    # continue to grow in number.
    def __init__(  # pylint: disable=too-many-arguments
        self,
        req_key="json",
        resp_key="result",
        force_json=True,
        # TODO: deprecate `json_module` param and change name to something
        # more generic, e.g. `content_parser`, with a specified interface
        json_module=simplejson,
        expected_content_type=JSON_CONTENT_TYPE,
        handle_unexpected_content_types=False,
    ):
        # type: (str, str, bool, Any, str, bool) -> None
        """Instantiate the middleware object

        :param req_key: (default ``'json'``) the key on the
            ``req.context`` object where the parsed request body
            will be stored
        :param resp_key: (default ``'result'``) the key on the
            ``req.context`` object where the response parser will
            look to find data to serialize into the response body
        :param force_json: (default ``True``) whether requests
            and responses for resources *without* any defined
            Marshmallow schemas should be parsed as json anyway.
        :param json_module: (default ``simplejson``) the json module to
            use for  (de)serialization if no schema is available on a
            resource and ``force_json`` is ``True`` - if you would like
            to use an alternative serializer to the stdlib ``json``
            module for your Marshmallow schemas, you will have to
            specify using a schema metaclass, as defined in the
            `Marshmallow documentation`_
        :param expected_content_type: the expected CONTENT_TYPE header
            corresponding to content that should be parsed by the
            Marshmallow schema. By default, responses that
            have a specified content type other than `expected_content_type`
            will be ignored by this middleware. See
            `handle_unexpected_content_types` for more options.
        :param handle_unexpected_content_types: whether content types other
            than the `expected_content_type` should be handled, or
            whether they should be ignored and allowed to pass through
            to the application or to other middlewares. This defaults to
            True. If it is set to False, the middleware will attempt to
            parse ALL requests with the provided json_module and/or
            Marshmallow schema.

            .. _marshmallow documentation: http://marshmallow.readthedocs.io/
                en/latest/api_reference.html#marshmallow.Schema.Meta

        """
        log.debug(
            "Marshmallow.__init__(%s, %s, %s, %s)",
            req_key,
            resp_key,
            force_json,
            json_module,
        )
        self._req_key = req_key
        self._resp_key = resp_key
        self._force_json = force_json
        self._json = json_module
        self._expected_content_type = expected_content_type
        self._handle_unexpected_content_types = handle_unexpected_content_types

    @staticmethod
    def _get_specific_schema(resource, method, msg_type):
        # type: (object, str, str) -> Optional[Schema]
        """Return a specific schema or None

        If the provided resource has defined method-specific schemas
        or method-request/response-specific schemas, return that
        schema. If there are multiple schemas defined, the more
        specific ones will take precedence.

        Examples:
            - 'get_schema' for a 'GET' request & response
            - `post_schema' for a 'POST' request & response
            - 'post_request_schema' for a 'POST' request
            - 'post_response_schema' for a 'POST' response

        Return ``None`` if no matching schema exists

        :param resource: the resource object passed to
            ``process_response`` or ``process_resource``
        :param method: the (case-insensitive) HTTP method used
            for the request, e.g. 'GET' or 'POST'
        :param msg_type: a string 'request' or 'response'
            representing whether this was called from
            ``process_response`` or ``process_resource``
        """
        log.debug(
            "Marshmallow._get_specific_schema(%s, %s, %s)",
            resource,
            method,
            msg_type,
        )

        sch_name = "%s_%s_schema" % (method.lower(), msg_type)
        specific_schema = getattr(resource, sch_name, None)
        if specific_schema is not None:
            return specific_schema  # type: ignore

        sch_name = "%s_schema" % method.lower()
        specific_schema = getattr(resource, sch_name, None)
        return specific_schema  # type: ignore

    @classmethod
    def _get_schema(cls, resource, method, msg_type):
        # type: (object, str, str) -> Optional[Schema]
        """Return a method-specific schema, a generic schema, or None

        If the provided resource has defined method-specific schemas
        or method-request/response-specific schemas, return that
        schema. If there are multiple schemas defined, the more
        specific ones will take precedence.

        Examples:
            - 'get_schema' for a 'GET' request & response
            - `post_schema' for a 'POST' request & response
            - 'post_request_schema' for a 'POST' request
            - 'post_response_schema' for a 'POST' response

        Otherwise, if the provided resource has defined a generic
        schema under ``resource.schema``, return that schema.

        Return ``None`` if neither of the above is found

        :param resource: the resource object passed to
            ``process_response`` or ``process_resource``
        :param method: the (case-insensitive) HTTP method used
            for the request, e.g. 'GET' or 'POST'
        :param msg_type: a string 'request' or 'response'
            representing whether this was called from
            ``process_response`` or ``process_resource``
        """
        log.debug(
            "Marshmallow._get_schema(%s, %s, %s)", resource, method, msg_type
        )
        specific_schema = cls._get_specific_schema(resource, method, msg_type)
        if specific_schema is not None:
            return specific_schema
        return getattr(resource, "schema", None)  # type: ignore

    def _content_is_expected_type(self, content_type):
        # type: (str) -> bool
        """Check if the provided content type is json.

        This uses similar code to client_accepts in falcon.request.

        If content type is not provided, assume json for backwards
        compatibility.

        :param content_type: a content type string from the request object
            (e.g., 'application/json', 'text/csv',
            'application/json;encoding=latin1')

        :return: true if the given content type represents JSON
        """
        # PERF(kgriffs): Usually the following will be true, so
        # try it first.
        if content_type == self._expected_content_type or content_type is None:
            return True

        # Fall back to full-blown parsing
        try:
            return bool(
                mimeparse.quality(content_type, self._expected_content_type)
                != 0.0
            )
        except ValueError:
            return False

    def process_resource(self, req, resp, resource, params):
        # type: (Request, Response, object, dict) -> None
        """Deserialize request body with any resource-specific schemas

        Store deserialized data on the ``req.context`` object
        under the ``req_key`` provided to the class constructor
        or on the ``json`` key if none was provided.

        If a Marshmallow schema is defined on the passed ``resource``,
        use it to deserialize the request body.

        If no schema is defined and the class was instantiated with
        ``force_json=True``, request data will be deserialized with
        any ``json_module`` passed to the class constructor or
        ``simplejson`` by default.

        :param falcon.Request req: the request object
        :param falcon.Response resp: the response object
        :param object resource: the resource object
        :param dict params: any parameters parsed from the url

        :rtype: None
        :raises falcon.HTTPBadRequest: if the data cannot be
            deserialized or decoded
        """
        log.debug(
            "Marshmallow.process_resource(%s, %s, %s, %s)",
            req,
            resp,
            resource,
            params,
        )
        if req.content_length in (None, 0):
            return

        if (
            not self._handle_unexpected_content_types
            and not self._content_is_expected_type(req.content_type)
        ):
            log.info(
                "Input type (%s) is not of expected type (%s), "
                "skipping deserialization",
                req.content_type,
                self._expected_content_type,
            )
            return

        sch = self._get_schema(resource, req.method, "request")

        if sch is not None:
            if not isinstance(sch, Schema):
                raise TypeError(
                    "The schema and <method>_schema properties of a resource "
                    "must be instantiated Marshmallow schemas."
                )

            try:
                body = get_stashed_content(req)
                parsed = self._json.loads(body)
            except UnicodeDecodeError:
                raise HTTPBadRequest("Body was not encoded as UTF-8")
            except self._json.JSONDecodeError:
                raise HTTPBadRequest("Request must be valid JSON")

            if MARSHMALLOW_2:
                data, errors = sch.load(parsed)

                if errors:
                    raise HTTPUnprocessableEntity(
                        description=self._json.dumps(errors)
                    )
            else:
                # Marshmallow 3 or higher raises a ValidationError
                # instead of returning a (data, errors) tuple.
                try:
                    data = sch.load(parsed)
                except ValidationError as exc:
                    raise HTTPUnprocessableEntity(
                        description=self._json.dumps(exc.messages)
                    )
                except Exception as exc:
                    raise HTTPUnprocessableEntity(
                        description=self._json.dumps({"error": exc})
                    )

            req.context[self._req_key] = data

        elif self._force_json:

            body = get_stashed_content(req)
            try:
                req.context[self._req_key] = self._json.loads(body)
            except (ValueError, UnicodeDecodeError):
                raise HTTPBadRequest(
                    description=(
                        "Could not decode the request body, either because "
                        "it was not valid JSON or because it was not encoded "
                        "as UTF-8."
                    )
                )

    def process_response(self, req, resp, resource, req_succeeded):
        # type: (Request, Response, object, bool) -> None
        """Serialize the result and dump it in ``resp.body``

        Look in the ``req.context`` for the ``req_key`` provided to
        the constructor of this function, or ``result`` if not
        provided. If not found, return.

        If a Marshmallow schema is defined for the given ``resource``,
        use it to serialize the result.

        If no schema is defined and the class was instantiated with
        ``force_json=True``, request data will be serialized with
        any ``json_module`` passed to the class constructor or
        ``simplejson`` by default.

        :param falcon.Request req: the request object
        :param falcon.Response resp: the response object
        :param object resource: the resource object
        :param bool req_succeeded: whether the request was successful

        :raises falcon.HTTPInternalServerError: if the data found
            in the ``req.context`` object cannot be serialized
        """
        log.debug(
            "Marshmallow.process_response(%s, %s, %s, %s)",
            req,
            resp,
            resource,
            req_succeeded,
        )
        if self._resp_key not in req.context:
            return

        sch = self._get_schema(resource, req.method, "response")

        if sch is not None:
            if not isinstance(sch, Schema):
                raise TypeError(
                    "The schema and <method>_schema properties of a resource "
                    "must be instantiated Marshmallow schemas."
                )

            if MARSHMALLOW_2:
                data, errors = sch.dumps(req.context[self._resp_key])

                if errors:
                    raise HTTPInternalServerError(
                        title="Could not serialize response",
                        description=self._json.dumps(errors),
                    )
            else:
                # Marshmallow 3 or higher raises a ValidationError
                # instead of returning a (data, errors) tuple.
                try:
                    data = sch.dumps(req.context[self._resp_key])
                except ValidationError as exc:
                    raise HTTPInternalServerError(
                        title="Could not serialize response",
                        description=self._json.dumps(exc.messages),
                    )
                except Exception as exc:
                    # For some reason Marshmallow does not intercept e.g.
                    # ValueErrors and throw a ValidationError when a value
                    # is of the wrong type, instead letting the excpetion
                    # percolate up.
                    raise HTTPInternalServerError(
                        title="Could not serialize response",
                        description=self._json.dumps({"error": str(exc)}),
                    )

            resp.body = data

        elif self._force_json:
            try:
                resp.body = self._json.dumps(req.context[self._resp_key])
            except TypeError:
                raise HTTPInternalServerError(
                    title="Could not serialize response",
                    description=(
                        "The server attempted to serialize an object that "
                        "cannot be serialized. This is likely a server-side "
                        "bug."
                    ),
                )
