from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ActiveTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if user.status != "active":
            raise AuthenticationFailed("Account is not active.")
        return user, token
