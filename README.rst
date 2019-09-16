falcon-marshmallow
==================

.. image:: https://gitlab.com/mplanchard/falcon-marshmallow/badges/master/pipeline.svg
   :target: https://gitlab.com/mplanchard/falcon-marshmallow/pipelines/
   
.. image:: https://gitlab.com/mplanchard/falcon-marshmallow/badges/master/coverage.svg
   :target: https://gitlab.com/mplanchard/falcon-marshmallow/pipelines/

-----------------------------------------------------------------

Marshmallow serialization/deserialization middleware for Falcon

=============   ==================================================
Maintained By   `Matthew Planchard`_
Author          `Matthew Planchard`_
License         `MIT`_
Compatibility   Python 2.7+, 3.4+
Contributors    `@timc13`_, `Your Name Here!`_
=============   ==================================================

**Note:** this package is a fork of `ihiji/falcon-marshmallow`_, of which I am the original
author. The project was abandoned after Ihiji was purchased, so I'm maintaining it here
now. Issues opened on the original fork will not be seen or resolved.

.. _Matthew Planchard: https://github.com/mplanchard
.. _MIT: https://github.com/mplanchard/falcon-marshmallow/blob/master/LICENSE
.. _Your Name Here!: Contributing_
.. _@timc13: https://github.com/timc13
.. _ihiji/falcon-marshmallow: https://github.com/ihiji/falcon-marshmallow

Installation
------------

Install from `pypi <https://pypi.org/project/falcon-marshmallow/>`_ with::

    pip install falcon_marshmallow

Usage
-----

The primary middleware provided by this package is called ``Marshmallow``. To
use it, simply add it to your Falcon app instantiation:

.. code:: python 

    from falcon import API
    from falcon_marshmallow import Marshmallow

    app = API(
        middleware=[
            Marshmallow(),
        ]
    )

The Marshmallow middleware looks for schemas defined on your resources, and,
if it finds an applicable schema, uses it to serialize incoming requests
and deserialize outgoing responses. Schema attributes should either be
named ``schema`` or ``<method>_schema``, where ``<method>`` is an HTTP method. If
both an appropriate method schema and a general schema are defined, the
method schema takes precedence.

Marshmallow assumes JSON serialization and uses the standard library's
``json`` module, but if you specify a different serialization module in a
schema's Meta class, that will be seamlessly integrated into this library's
(de)serialization.

By default, if no schema is found, the Marshmallow middleware will still
attempt to (de)serialize data using the ``simplejson`` module. This can be
disabled when instantiating the middleware by setting ``force_json`` to
``False``.

Two extra middleware classes are provided for convenience:

* ``JSONEnforcer`` raises an ``HTTPNotAcceptable`` error if the client request
  indicates that it will does not accept JSON and ensures that the Content-Type
  of requests is "application/json" for specified HTTP methods (default PUT,
  POST, PATCH).
* ``EmptyRequestDropper`` returns an ``HTTPBadRequest`` if a request has
  a non-zero Content-Length header with an empty body


Examples
++++++++


Standard ReST Resource
~~~~~~~~~~~~~~~~~~~~~~

Let's look at a standard ReST resource corresponding to a Philosopher
resource in our chosen data store:

.. code:: python

    from datetime import date
    from random import randint

    from marshmallow import fields, Schema
    from falcon import API
    from falcon_marshmallow import Marshmallow
    from wsgiref import simple_server


    class MyDataStore:
        """Whatever DB driver you like"""

        def get(self, table, phil_id):
            print('I got item with id %s from %s' % (phil_id, table))
            return {
                'id': phil_id,
                'name': 'Albert Camus',
                'birth': date(1913, 11, 7),
                'death': date(1960, 1, 4),
                'schools': ['existentialism', 'absurdism'],
                'works': ['The Stranger', 'The Myth of Sissyphus']
            }

        def insert(self, table, obj):
            print('I inserted %s into %s' % (obj, table))
            return {
                'id': randint(1, 100),
                'name': 'Søren Kierkegaard',
                'birth': date(1813, 5, 5),
                'death': date(1855, 11, 11),
                'schools': ['existentialism'],
                'works': ['Fear and Trembling', 'Either/Or']
            }


    class Philosopher(Schema):
        """Philosopher schema"""
        id = fields.Integer()
        name = fields.String()
        birth = fields.Date()
        death = fields.Date()
        schools = fields.List(fields.String())
        works = fields.List(fields.String())


    class PhilosopherResource:

        schema = Philosopher()

        def on_get(self, req, resp, phil_id):
            """req['result'] will be automatically serialized

            The key in which results are stored can be customized when
            the middleware is instantiated.
            """
            req.context['result'] = MyDataStore().get('philosophers', phil_id)


    class PhilosopherCollection:

        schema = Philosopher()

        def on_post(self, req, resp):
            """req['json'] contains our deserialized data

            The key in which deserialized data can be stored can be
            customized when the middleware is instantiated.
            """
            inserted = MyDataStore().insert('philosophers', req.context['json'])
            req.context['result'] = inserted


    app = API(middleware=[Marshmallow()])

    app.add_route('/v1/philosophers', PhilosopherCollection())
    app.add_route('/v1/philosophers/{phil_id}', PhilosopherResource())


    if __name__ == '__main__':
        svr = simple_server.make_server('127.0.0.1', 8080, app)
        svr.serve_forever()

Done!

When parsing a request body, if it cannot be decoded or its JSON
is malformed, an HTTPBadRequest error will be raised. If the
deserialization of the request body fails due to schema validation errors,
an HTTPUnprocessableEntity error will be raised.

We can test our new server easily enough using the ``requests`` library:

.. code:: python

    >>> import requests

    # - GET some philosopher - #

    >>> resp = requests.get('http://127.0.0.1:8080/v1/philosophers/12')

    >>> resp.text
    '{"birth": "1913-11-07", "id": 12, "death": "1960-01-04", "works": ["The Stranger", "The Myth of Sissyphus"], "schools": ["existentialism", "absurdism"], "name": "Albert Camus"}'

    >>> resp.json()
    {'birth': '1913-11-07',
     'death': '1960-01-04',
     'id': 12,
     'name': 'Albert Camus',
     'schools': ['existentialism', 'absurdism'],
     'works': ['The Stranger', 'The Myth of Sissyphus']}

    # - POST a new philosopher - #

    >>> post_data = resp.json()

    >>> import json

    >>> presp = requests.post('http://127.0.0.1:8080/v1/philosophers', data=json.dumps(post_data))

    >>> presp.json()
    {'birth': '1813-05-05',
     'death': '1855-11-11',
     'id': 100,
     'name': 'Søren Kierkegaard',
     'schools': ['existentialism'],
     'works': ['Fear and Trembling', 'Either/Or']}


    # - Try to POST bad data - #

    >>> post_data['birth'] = 'not a date'

    >>> presp = requests.post('http://127.0.0.1:8080/v1/philosophers', data=json.dumps(post_data))

    >>> presp
    <Response [422]>

    >>> presp.json()
    {'description': '{"birth": ["Not a valid date."]}',
     'title': '422 Unprocessable Entity'}

Customization
+++++++++++++

Customization is effected by keyword arguments to the middleware constructor.
The constructor takes the following arguments:

* ``req_key`` (default ``json``) - the key on the request's ``context``
  dict on which to store parsed request data
* ``resp_key`` (default ``result``) - the key on the request's ``context``
  dict in which data to be serialized for a response should be stored
* ``force_json`` (default ``True``) - attempt to (de)serialize request
  and response bodies to/from JSON even if no schema is defined for a resource
* ``json_module`` (default ``simplejson``) - the module to use for
  (de)serialization; must implement the public interface of the ``json``
  standard library module
  

A Note on Python 2
++++++++++++++++++

Python 2 will be at its End of Life (EoL) `at the end of 2019 <https://pythonclock.org/>`_.
This package is relatively simple, though, and Python 2 compatibility is 
therefore not a huge burden to maintain. As such, we will continue to
maintain Python 2 compatibility after its EoL, until and unless we decide
that maintaining Python 2 compatibility puts our users at risk due to
potential security vulnerabilities, we feel that the burden of maintaining
Python 2 compatibility has become too high for our maintainers, or we determine 
that we can provide a significant increase in value by dropping Python 2support.

In any of those cases, we will try to clearly communicate the change with a major
version bump.

Contributing
------------

Contributions are welcome. Please feel free to raise Issues, submit PRs,
fix documentation typos, etc. If opening a PR, please be sure to run
tests, and ensure that your additions are compatible with Python 2.7, 3.4,
and above.

Ideally, PRs should have tests, but feel free to open a PR with or without
them. The maintainers will either suggest some tests for you to add, or,
if you are not able to add tests yourself, we may open a PR against your
branch with some added tests before merging.

Development requires that you have Python 3 available on your path.

Development
+++++++++++

To set up a local virtual environment with all required packages installed,
run::

  make setup

If you are using VSCode, the `.vscode/settings.json` file included in this
project should now be automatically configured to autoformat on save and
to perform all of the lint checks that are required for this package.

Linting
+++++++

The linting checks that run in CI can be manually run locally with::

  make lint

Note that this will automatically create a local virtual environment for
you if `make setup` has not yet been run.

Testing
+++++++

To run tests against Python 2.7 and 3.4 forward, you can just run::

  make test

Note that this will automatically create a local virtual environment for
you if `make setup` has not yet been run.

Testing against all environments of course requires that you have the
requisite Python executables available on your `PATH`. If you don't, you
will get "interpreter not found" errors for the missing python versions.

To run against a particular version of Python, use, for example::

  TESTENV=py37 make test-env

Where `TESTENV` is any of the environments configured in `tox.ini`, or
any of tox's standard environments (e.g. `py36`, `py37`, etc.).
