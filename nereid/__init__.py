# -*- coding: UTF-8 -*-
'''
    nereid

    A microframework based on Flask, Werkzeug and powered by the 
    Tryton ERP.

    It replicates the Flask API for most of the system

    :copyright: (c) 2010-2011 by Openlabs Technologies & Consulting (P) Ltd.
    :license: BSD, see LICENSE for more details
'''

# utilities we import from Werkzeug and Jinja2 that are unused
# in the module but are exported as public interface.
from werkzeug import abort, redirect
from jinja2 import Markup, escape

from .globals import current_app, g, request, \
    session, _request_ctx_stack, transaction
from .templating import render_template, render_template_string
from .helpers import flash, get_flashed_messages, jsonify, url_for, \
    login_required

from .application import Nereid, Request, Response, cache
from .session import Session

