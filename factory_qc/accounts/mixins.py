from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from .roles import can_manage_master_data, get_role


class MasterDataAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Master-data pages: anonymous users go to login (LoginRequiredMixin);
    logged-in users who are not Quality Engineer/Admin get 403.
    """

    def test_func(self):
        return can_manage_master_data(self.request.user)


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Dashboard pages: the user's primary role must equal `required_role`."""
    required_role = None

    def test_func(self):
        return get_role(self.request.user) == self.required_role
