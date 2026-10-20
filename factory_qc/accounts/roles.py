"""Role helpers. A user's role comes from their group; superusers are the Plant Manager."""
QUALITY_ENGINEER = "Quality Engineer"
INSPECTOR = "Inspector"
SUPERVISOR = "Supervisor"
PLANT_MANAGER = "Plant Manager"  # = superuser (Admin)

# Where each role lands after login.
DASHBOARD_URL_NAMES = {
    PLANT_MANAGER: "accounts:plant_manager_dashboard",
    QUALITY_ENGINEER: "accounts:engineer_dashboard",
    SUPERVISOR: "accounts:supervisor_dashboard",
    INSPECTOR: "accounts:inspector_dashboard",
}


def get_role(user):
    """
    Return the user's primary role, or None if they have none.
    Business rule: superuser always wins; if someone sits in several groups,
    the order is Quality Engineer > Supervisor > Inspector.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return PLANT_MANAGER
    names = set(user.groups.values_list("name", flat=True))
    for role in (QUALITY_ENGINEER, SUPERVISOR, INSPECTOR):
        if role in names:
            return role
    return None


def can_manage_master_data(user):
    """Business rule: only Quality Engineers and Admin (superuser) may touch master data."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=QUALITY_ENGINEER).exists()
