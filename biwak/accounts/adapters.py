from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    """Nobody signs up: people are invited (specs/access.md)"""

    def is_open_for_signup(self, request):
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Google sign-in only for existing, active people, matched by email"""

    def is_open_for_signup(self, request, sociallogin):
        return False
