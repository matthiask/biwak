"""allauth's sign-in forms (``ACCOUNT_FORMS``), refusing codes to people
whose organization requires single sign-on (specs/sso.md): the views send
them to their identity provider instead (``signin.login`` and
``signin.request_login_code``)"""

from allauth.account.forms import LoginForm, RequestLoginCodeForm
from django.core.exceptions import ValidationError

from biwak.accounts import sso
from biwak.accounts.models import User


def _check_sso(form, email, request):
    """``ValidationError`` naming the provider for people whose organization
    requires it, remembering where to send them (``form.sso_url``)"""
    form.sso_url = None
    if not email:
        return
    user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if user is not None and (org := sso.required_organization(user)):
        next_url = ""
        if request is not None:
            next_url = request.POST.get("next") or request.GET.get("next") or ""
        form.sso_url = sso.idp_login_url(user, next_url=next_url)
        raise ValidationError(sso.uses_sso_message(org))


class SSOLoginForm(LoginForm):
    """The login page's address, which asks for a code"""

    def clean_login(self):
        login = super().clean_login()
        _check_sso(self, login, self.request)
        return login


class SSORequestLoginCodeForm(RequestLoginCodeForm):
    def __init__(self, *args, **kwargs):
        from allauth.core import context

        super().__init__(*args, **kwargs)
        self.request = context.request

    def clean_email(self):
        _check_sso(self, self.cleaned_data.get("email"), self.request)
        return super().clean_email()
