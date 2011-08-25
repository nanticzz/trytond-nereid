# This file is part of Nereid.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
'''
    nereid_trytond.party

    Partner Address is also considered as the login user

    :copyright: (c) 2010 by Sharoon Thomas.
    :license: BSD, see LICENSE for more details
'''
import random
import string
try:
    import hashlib
except ImportError:
    hashlib = None
    import sha

from wtforms import Form, TextField, IntegerField, SelectField, validators, \
    PasswordField
from wtfrecaptcha.fields import RecaptchaField
from nereid import request, url_for, render_template, login_required, flash
from nereid.globals import session, current_app
from werkzeug import redirect, abort
from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Eval, Bool, Not
from trytond.config import CONFIG


class RegistrationForm(Form):
    "Simple Registration form"
    name = TextField('Name', [validators.Required(),])
    company = TextField('Company')
    street = TextField('Street', [validators.Required(),])
    streetbis = TextField('Street (Bis)')
    zip = TextField('Post Code', [validators.Required(),])
    city = TextField('City', [validators.Required(),])
    country = SelectField('Country', [validators.Required(),], coerce=int)
    subdivision = IntegerField('State/Country', [validators.Required()])
    email = TextField('e-mail', [validators.Required(), validators.Email()])
    if 're_captcha_public' in CONFIG.options:
        captcha = RecaptchaField(
            public_key=CONFIG.options['re_captcha_public'], 
            private_key=CONFIG.options['re_captcha_private'], secure=True)
    password = PasswordField('New Password', [
        validators.Required(),
        validators.EqualTo('confirm', message='Passwords must match')])
    confirm = PasswordField('Confirm Password')


class AddressForm(Form):
    "A Form resembling the party.address"
    name = TextField('Name', [validators.Required(),])
    street = TextField('Street', [validators.Required(),])
    streetbis = TextField('Street (Bis)')
    zip = TextField('Post Code', [validators.Required(),])
    city = TextField('City', [validators.Required(),])
    country = SelectField('Country', [validators.Required(),], coerce=int)
    subdivision = IntegerField('State/Country', [validators.Required()])


class NewPasswordForm(Form):
    "Form to set a new password"
    password = PasswordField('New Password', [
        validators.Required(),
        validators.EqualTo('confirm', message='Passwords must match')])
    confirm = PasswordField('Repeat Password')


class ChangePasswordForm(NewPasswordForm):
    "Form to change the password"
    old_password = PasswordField('Old Password')


STATES = {
    'readonly': Not(Bool(Eval('active'))),
}


# pylint: disable-msg=E1101
class AdditionalDetails(ModelSQL, ModelView):
    "Additional Details for Address"
    _name = "address.additional_details"
    _description = __doc__
    _rec_name = 'value'
    
    def get_types(self):
        """
        Wrapper to convert _get_types dictionary 
        into a `list of tuple` for the use of Type Selection field
        
        This hook will scan all methods which start with _type_address_extend
        
        Your hook extension should look like:
                
        def _type_address_extend_<name>(self, cursor, user, context=None):
            return {
                        '<name>': '<value>'
            }
        
        An example from ups:
        
        return {'type': 'value'
            }
        
        :return: the list of tuple for Selection field
        """
        type_dict = {}
        for attribute in dir(self):
            if attribute.startswith('_type_address_extend'):
                type_dict.update(getattr(self, attribute).__call__())
        return type_dict.items()

    type = fields.Selection('get_types', 'Type', required=True, states=STATES,
        select=1)
    value = fields.Char('Value', select=1, states=STATES)
    comment = fields.Text('Comment', states=STATES)
    address = fields.Many2One('party.address', 'Address', required=True,
        ondelete='CASCADE', states=STATES, select=1)
    active = fields.Boolean('Active', select=1)
    sequence = fields.Integer('Sequence')

    def default_active(self):
        return True
        
    def _type_address_extend_default(self):
        return {
            'dob': 'Date of Birth',
            'other': 'Other',
        }
    
AdditionalDetails()


class Address(ModelSQL, ModelView):
    """An address is considered as the equivalent of a user
    in a conventional Web application. Hence, the username and
    password are stored against the party.address object.
    """
    _name = 'party.address'

    registration_form = RegistrationForm

    #: The email to which all application related emails like
    #: registration, password reset etc is managed
    email = fields.Many2One('party.contact_mechanism', 'E-Mail',
        domain=[('party', '=', Eval('party')), ('type', '=', 'email')], 
        depends=['party'])

    #: Similar to email
    phone = fields.Many2One('party.contact_mechanism', 'Phone',
        domain=[('party', '=', Eval('party')), ('type', '=', 'phone')], 
        depends=['party'])

    #: The password is the user password + the salt, which is
    #: then hashed together
    password = fields.Sha('Password')

    #: The salt which was used to make the hash is separately
    #: stored. Needed for 
    salt = fields.Char('Salt', size=8)

    #: A unique activation code required to match the user's request
    #: for activation of the account.
    activation_code = fields.Char('Unique Activation Code')
    
    # Extra fields to cater to extended registration
    additional_details = fields.One2Many('address.additional_details', 
        'address', 'Additional Details', states=STATES)

    def __init__(self):
        super(Address, self).__init__()
        self._sql_constraints += [
            ('unique_email', 'UNIQUE(email)',
                'email must be unique.'),
            ('unique_activation_code', 'UNIQUE(activation_code)',
                'Activation code must be unique.'),
        ]
        self._error_messages.update({
            'no_email': 'The user does not have an email assigned'
            })
        self._rpc.update({
            'create_web_account': True,
            'reset_web_account': True
            })

    def _activate(self, address_id, activation_code):
        "Activate the address account"
        address = self.browse(address_id)
        assert address.activation_code == activation_code, 'Invalid Act Code'
        return self.write(address.id, {'activation_code': False})

    @login_required
    def change_password(self):
        "Changes the password"
        form = ChangePasswordForm(request.form)
        if request.method == 'POST' and form.validate():
            self.write(request.nereid_user.id, 
                {'password': form.password.data})
            flash('Your password has been successfully changed! '
                'Please login again')
            session.pop('user')
            return redirect(url_for('nereid.website.login'))
        return render_template('change-password.jinja', 
            change_password_form=form)

    @login_required
    def new_password(self):
        """Create a new password, unlike change password this does not demand
        the old password. And hence this method will check in the session for
        a parameter called allow_new_password which has to be True. This acts
        as a security against attempts to POST to this method and changing 
        password.

        This is intended to be used when a user requests for a password reset.
        """
        form = NewPasswordForm(request.form)
        if request.method == 'POST' and form.validate():
            if not session.get('allow_new_password', False):
                current_app.logger.debug('New password not allowed in session')
                abort(403)
            self.write(request.nereid_user.id, 
                {'password': form.password.data})
            session.pop('allow_new_password')
            flash('Your password has been successfully changed! '
                'Please login again')
            session.pop('user')
            return redirect(url_for('nereid.website.login'))
        return render_template('new-password.jinja', password_form=form)

    def activate(self, address_id, activation_code):
        """A web request handler for activation

        :param activation_code: A 12 character activation code indicates reset
            while 16 character activation code indicates a new registration
        """
        try:
            self._activate(address_id, activation_code)
            flash('Your account has been activated')

            # Log the user in.
            session['user'] = address_id

            # Redirect the user to the correct location according to the type
            # of activation code.
            if len(activation_code) == 12:
                session['allow_new_password'] = True
                return redirect(url_for('party.address.new_password'))
            elif len(activation_code) == 16:
                return redirect(url_for('nereid.website.home'))
        except AssertionError:
            flash('Invalid Activation Code')
        return redirect(url_for('nereid.website.login'))

    def create_act_code(self, address, length=16):
        """Create activation code
        :param address: ID of the addresss
        """
        act_code = ''.join(
                random.sample(string.letters + string.digits, length))
        exists = self.search([('activation_code', '=', act_code)])
        if exists:
            return self.create_act_code(address)
        return self.write(address, {'activation_code': act_code})

    def create_web_account(self, ids, return_password=False):
        """Create a new web account for given address

        This is a Tryton only interface

        :return: The set password
        """
        address = self.browse(ids[0])
        if not address.email:
            self.raise_user_error('no_email')

        password = ''.join(
            random.sample(string.letters + string.digits, 16))
        self.write(address.id, {'password': password})
        return return_password and password or True

    def registration(self):
        if 're_captcha_public' in CONFIG.options:
            register_form = self.registration_form(request.form, 
                captcha={'ip_address': request.remote_addr})
        else:
            register_form = self.registration_form(request.form)

        register_form.country.choices = [
            (c.id, c.name) for c in request.nereid_website.countries
            ]
        if request.method == 'POST' and register_form.validate():
            address_obj = self.pool.get('party.address')
            contact_mech_obj = self.pool.get('party.contact_mechanism')
            party_obj = self.pool.get('party.party')

            registration_data = register_form.data

            # First search if an address with the email already exists
            existing = contact_mech_obj.search([
                ('value', '=', registration_data['email']),
                ('type', '=', 'email'),
                ('party.company', '=', request.nereid_website.company.id),
                ])
            if existing:
                flash('A registration already exists with this email. '
                    'Please contact customer care')
            else:
                # Create Party
                party_id = party_obj.create({
                    'name': registration_data['company'] or \
                        registration_data['name'],
                    'company': request.nereid_website.company.id,
                    'addresses': [
                        ('create', {
                            'name': registration_data['name'],
                            'street': registration_data['street'],
                            'streetbis': registration_data['streetbis'],
                            'zip': registration_data['zip'],
                            'city': registration_data['city'],
                            'country': registration_data['country'],
                            'subdivision': registration_data['subdivision'],
                            'password': registration_data['password']
                            })],
                    })
                party = party_obj.browse(party_id)

                # Create email as contact mech and assign as email
                contact_mech_id = contact_mech_obj.create({
                        'type': 'email',
                        'party': party.id,
                        'email': registration_data['email'],
                    })
                address_obj.write(party.addresses[0].id, 
                    {'email': contact_mech_id})
                address_obj.create_act_code(party.addresses[0].id)

                flash('Registration Complete. Check your email for activation')
                return redirect(request.args.get('next', 
                    url_for('nereid.website.home')))
        return render_template('registration.jinja', form=register_form)

    def reset_account(self):
        """Reset the password for the user

        This is a web interface
        """
        contact_mech_obj = self.pool.get('party.contact_mechanism')

        if request.method == 'POST':
            contact = contact_mech_obj.search([
                ('value', '=', request.form['email']),
                ('type', '=', 'email'),
                ('party.company', '=', request.nereid_website.company.id),
                ])
            if not contact:
                flash('Invalid email address')
                return render_template('reset-password.jinja')
            address = self.search([('email', '=', contact[0])])
            if not address:
                flash('Email is not associated with any account.')
                return render_template('reset-password.jinja')

            self.create_act_code(address[0], length=12)
            flash('An email has been sent to your account for resetting'
                ' your credentials')
            return redirect(url_for('nereid.website.login'))

        return render_template('reset-password.jinja')

    def authenticate(self, email, password):
        """Assert credentials and if correct return the
        browse record of the user

        :param email: email of the user
        :param password: password of the user
        :return: Browse Record or None
        """
        contact_mech_obj = self.pool.get('party.contact_mechanism')

        guest_user = self.browse(current_app.guest_user)
        contact = contact_mech_obj.search([
            ('value', '=', email),
            ('type', '=', 'email'),
            ('party.company', '=', request.nereid_website.company.id),
            ('party', '!=', guest_user.party.id)
            ])
        if not contact:
            current_app.logger.debug('%s not found' % email)
            return None

        ids = self.search([
            ('email', '=', contact[0])
            ])
        if not ids or len(ids) > 1:
            current_app.logger.debug('%s not attached to addresses' % email)
            return None

        address = self.browse(ids[0])
        if address.activation_code and len(address.activation_code) == 16:
            current_app.logger.debug('%s not activated' % email)
            flash("Your account has not been activated yet!")
            return False # False so to avoid `invalid credentials` flash

        password += address.salt or ''

        if isinstance(password, unicode):
            password = password.encode('utf-8')

        if hashlib:
            password_sha = hashlib.sha1(password).hexdigest()
        else:
            password_sha = sha.new(password).hexdigest()

        if password_sha == address.password:
            return address

        return None

    def _convert_values(self, values):
        if 'password' in values and values['password']:
            values['salt'] = ''.join(random.sample(
                string.ascii_letters + string.digits, 8))
            values['password'] += values['salt']
        return values

    def create(self, values):
        """
        Create, but add salt before saving

        :param values: Dictionary of Values
        """
        return super(Address, self).create(self._convert_values(values))

    def write(self, ids, values):
        """
        Update salt before saving

        :param ids: IDs of the records
        :param values: Dictionary of values
        """
        return super(Address, self).write(ids, self._convert_values(values))

    @login_required
    def edit_address(self, address=None):
        form = AddressForm(request.form)
        form.country.choices = [
            (c.id, c.name) for c in request.nereid_website.countries
            ]
        if address not in [a.id for a in request.nereid_user.party.addresses]:
            address = None
        if request.method == 'POST' and form.validate():
            if address is not None:
                self.write(address, {
                    'name': form.name.data,
                    'street': form.street.data,
                    'streetbis': form.streetbis.data,
                    'zip': form.zip.data,
                    'city': form.city.data,
                    'country': form.country.data,
                    'subdivision': form.subdivision.data,
                    })
            else:
                self.create({
                    'name': form.name.data,
                    'street': form.street.data,
                    'streetbis': form.streetbis.data,
                    'zip': form.zip.data,
                    'city': form.city.data,
                    'country': form.country.data,
                    'subdivision': form.subdivision.data,
                    'party': request.nereid_user.party.id,
                    })
            return redirect(url_for('party.address.view_address'))
        elif request.method == 'GET' and address:
            # Its an edit of existing address, prefill data
            record = self.browse(address)
            form = AddressForm(
                name=record.name,
                street=record.street,
                streetbis=record.streetbis,
                zip=record.zip,
                city=record.city,
                country=record.country.id,
                subdivision=record.subdivision.id
            )
            form.country.choices = [
                (c.id, c.name) for c in request.nereid_website.countries
            ]
        return render_template('address-edit.jinja', form=form, address=address)

    @login_required
    def view_address(self):
        "View the addresses of user"
        return render_template('address.jinja')

Address()


class Party(ModelSQL, ModelView):
    """Add company to the user"""
    _name = "party.party"

    # The company of the website(s) to which the user is affiliated. This 
    # allows websites of the same company to share authentication/users. It 
    # does not make business or technical sense to have website of multiple
    # companies share the authentication.
    company = fields.Many2One('company.company', 'Company')

Party()


class EmailTemplate(ModelSQL, ModelView):
    'add `url_for` to the template context'
    _name = 'electronic_mail.template'

    def template_context(self, record):
        context = super(EmailTemplate, self).template_context(record)
        context['url_for'] = url_for
        return context

EmailTemplate()
