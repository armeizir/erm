from django.contrib.auth.backends import ModelBackend
from django_auth_ldap.backend import LDAPBackend


class PLNLDAPBackend(LDAPBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username and username.lower().endswith("@plnbatam.com"):
            username = username[:-13]
        return super().authenticate(
            request,
            username=username,
            password=password,
            **kwargs
        )


class SuperuserOnlyModelBackend(ModelBackend):
    """
    Fallback login lokal hanya untuk superuser.
    User biasa tidak boleh login dengan password lokal.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(
            request,
            username=username,
            password=password,
            **kwargs
        )
        if user and user.is_superuser:
            return user
        return None