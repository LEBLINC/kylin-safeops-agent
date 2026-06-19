import os
import pytest


class TestLdapClientMock:
    def setup_method(self):
        os.environ["KYLIN_LDAP_MOCK"] = "true"
        from deploy.sso.ldap_client import LdapClient
        self.client = LdapClient()

    def test_authenticate_valid_user_correct_password(self):
        assert self.client.authenticate("admin", "kylin123") is True

    def test_authenticate_valid_user_wrong_password(self):
        assert self.client.authenticate("admin", "wrong") is False

    def test_authenticate_nonexistent_user(self):
        assert self.client.authenticate("nonexistent", "kylin123") is False

    def test_get_user_admin_has_admin_role(self):
        user = self.client.get_user("admin")
        assert user is not None
        assert "admin" in user.roles
        assert "operator" in user.roles

    def test_get_user_viewer_has_viewer_role(self):
        user = self.client.get_user("viewer")
        assert user is not None
        assert "viewer" in user.roles

    def test_get_user_nonexistent_returns_none(self):
        assert self.client.get_user("nonexistent") is None

    def test_mock_mode_no_network(self, monkeypatch):
        """mock mode should not trigger network connections"""
        assert self.client.mock is True
        assert self.client.authenticate("admin", "kylin123") is True
