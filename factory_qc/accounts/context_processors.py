from .roles import can_manage_master_data, get_role, INSPECTOR


def role(request):
    """Expose role helpers to every template."""
    user = request.user
    user_role = get_role(user) if user.is_authenticated else None
    return {
        "user_role": user_role,
        "can_manage_master": can_manage_master_data(user) if user.is_authenticated else False,
        "can_inspect": bool(
            user.is_authenticated and (user.is_superuser or user_role == INSPECTOR)
        ),
    }
