"""
Restplus Generic Base Resource
------------------------------
"""
from functools import wraps

import flask
import json
import sqlalchemy

from app.extensions import db
from app.extensions.api import http_exceptions

from flask_restplus_patched import (
    Parameters,
    resource,
)
from ..utils import bulk_decorate


SETTINGS_MAPPER = {
    'response_schemas': 'response',
    'parameters': 'parameters',
    'permissions': 'permission_required',
}


class GenericResource(resource.Resource):
    """
    Generic resource
    """

    model = None
    schema = None
    parameters = None
    permission_classes = None

    def __init__(self, *args, **kwargs):
        super(GenericResource, self).__init__(*args, **kwargs)

    @classmethod
    def _document_resource(cls, namespace, target=None):
        """
        Add corresponding decorators from ``flask_restplus_patched``
        to the specific methods of this generic resource
        """
        if not target:
            target = cls

        decorators_to_apply = []
        if target.permission_classes:
            for permission in target.permission_classes:
                decorators_to_apply.append(
                    namespace.permission_required(
                        permission()
                    )
                )

        # if target.parameters:
        #     decorators_to_apply.append(
        #         namespace.parameters(target.parameters())
        #     )

        if len(decorators_to_apply):
            for decorator in decorators_to_apply:
                for method in target.methods:
                    method_name = method.lower()
                    decorated_method_func = decorator(getattr(target, method_name))
                    setattr(target, method_name, decorated_method_func)

    def get_queryset(self):
        """
        Returns sqlalchemy query based on provided ``model``
        Fails with error if none is provided
        """
        assert self.model is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method."
            % self.__class__.__name__
        )

        queryset = self.model.query
        return queryset

    def get_schema(self):
        """
        Returns marshmallow schema provided in ``schema``
        """
        return self.schema

    def get_parameters(self):
        """
        Returns marshmallow parameters provided in ``parameters``
        """
        return self.parameters


class ListAPIResource(GenericResource):
    """
    Generic List resource
    """

    pagination_class = None

    def __init__(self, *args, **kwargs):
        super(ListAPIResource, self).__init__(*args, **kwargs)

    @classmethod
    def _document_resource(cls, namespace):
        """
        Add corresponding decorators from ``flask_restplus_patched``
        to the specific methods of this generic resource
        """

        # Apply necessary decorators that is common for generics
        # e.g. ``permission_classes`` and its decorators
        GenericResource._document_resource(namespace, target=cls)

        # Describe possible responses
        decorators_to_apply = cls._get_method_decorators(namespace)

        cls.get = wraps(cls.get)(
            bulk_decorate(decorators_to_apply)
        )(cls.get)

    def get(self, pagination_args=None, **kwargs):
        """
        Returns a list of objects
        """
        schema = self.get_schema()(many=True)

        queryset = self.get_queryset()
        if self.pagination_class:
            queryset = self._paginate(
                args=pagination_args,
                queryset=queryset
            )

        collection = schema.dump(
            queryset,
            many=True
        )

        if collection.errors:
            return flask.jsonify(
                collection.errors,
                status=400
            )

        return flask.jsonify(collection.data)

    def _paginate(self, args, queryset=None):
        """
        Perform pagination if ``pagination_class`` is provided.
        Modified ``queryset`` if provided or call ``self.get_queryset``
        """
        assert self.pagination_class, (
            "'%s' should both include a `pagination_class` attribute and "
            "it must be an instance of `Paramaters` (now '%s')"
            % (self.__class__.__name__, type(self.pagination_class))
        )

        pagination_parameters = self.pagination_class().dump(args).data

        if not queryset:
            queryset = self.get_queryset()
        return queryset.offset(
            pagination_parameters['offset']
        ).limit(
            pagination_parameters['limit']
        )

    @classmethod
    def get_method_input_output_settings(cls, namespace):
        settings = {
            'response_schemas': [
                namespace.response(code=400),
                namespace.response(model=cls.schema(many=True)),
            ],
        }
        if cls.pagination_class or cls.parameters:
            if cls.pagination_class:
                settings.update(
                    {
                        'parameters': namespace.parameters(cls.pagination_class())
                    }
                )
            elif cls.parameters:
                settings.update(
                    {
                        'parameters': namespace.parameters(cls.parameters())
                    }
                )
        if cls.permission_classes:
            settings.update(
                {
                    'permissions': [
                        namespace.permission_required(permission())
                        for permission in cls.permission_classes
                    ]
                }
            )

        return settings

    @classmethod
    def _get_method_decorators(cls, namespace):
        settings = cls.get_method_input_output_settings(namespace)
        decorators_list = settings['response_schemas'] + \
            [settings['parameters']] if 'parameters' in settings else [] + \
            settings['permissions'] if 'permissions' in settings else []
        return decorators_list


class CreateAPIResource(GenericResource):
    """
    Generic Create Resource
    """

    def __init__(self, *args, **kwargs):
        super(CreateAPIResource, self).__init__(*args, **kwargs)

    @classmethod
    def _document_resource(cls, namespace):
        """
        Add corresponding decorators from ``flask_restplus_patched``
        to the specific methods of this generic resource
        """

        # Apply necessary decorators that is common for generics
        # e.g. ``permission_classes`` and its decorators
        GenericResource._document_resource(namespace, target=cls)

        # Describe possible responses
        instance = cls()
        decorators_to_apply = instance._post_method_decoratos(namespace)

        cls.post = wraps(cls.post)(
            bulk_decorate(decorators_to_apply)
        )(cls.post)

    def post(self, args):
        """
        Create a new object
        """
        obj = self.model(**args)

        try:
            with db.session.begin():
                db.session.add(obj)
        except sqlalchemy.exc.IntegrityError as exception:
            http_exceptions.abort(
                code=409,
                message=str(exception)
            )

        return obj

    def post_method_settings(self):
        settings = {
            'response_schemas': [
                {'code': 400},
                {'code': 200, 'model': self.get_schema()},
            ],
        }
        if self.parameters:
            settings.update(
                {
                    'parameters': self.parameters()
                }
            )
        if self.permission_classes:
            settings.update(
                {
                    'permissions': [
                        permission()
                        for permission in self.permission_classes
                    ]
                }
            )

        return settings

    def _post_method_decorators(self, namespace):
        settings = self.post_method_settings()
        decorators_list = [
            namespace.response(**response) for response in settings['response_schemas']
        ] + [
            namespace.parameters(settings['parameters'])
        ] if 'parameters' in settings else [] + [
            namespace.permission_required(permission)
            for permission in settings['permissions']
        ] if 'permissions' in settings else []
        return decorators_list


class ListCreateAPIResource(ListAPIResource, CreateAPIResource):
    """
    Generic Resource to list and create objects
    """

    @classmethod
    def _document_resource(cls, namespace):
        """
        Add corresponding decorators from ``flask_restplus_patched``
        to the specific methods of this generic resource
        """

        # Apply necessary decorators that is common for generics
        # e.g. ``permission_classes`` and its decorators
        # GenericResource._document_resource(namespace, target=cls)
        instance = cls()
        get_method_decorators = cls._get_method_decorators(namespace)

        cls.get = wraps(cls.get)(
            bulk_decorate(get_method_decorators)
        )(cls.get)

        post_method_decoratos = instance._post_method_decorators(namespace)

        cls.post = wraps(cls.post)(
            bulk_decorate(post_method_decoratos)
        )(cls.post)

    def get(self, *args, **kwargs):
        return super(ListCreateAPIResource, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return super(ListCreateAPIResource, self).post(*args, **kwargs)

    def post_method_settings(self, *args, **kwargs):
        return super(ListCreateAPIResource, self).post_method_settings(*args, **kwargs)
