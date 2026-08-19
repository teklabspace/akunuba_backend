from app.core.permissions import Role


def ticket_scope_for_role(role: Role) -> str:
    """Which support tickets a role sees: "all" | "assigned" | "own".

    Single source of truth shared by GET /support/tickets and
    GET /support/analytics so the two can never disagree again (they did:
    an advisor's list showed every ticket while their analytics scope
    counted only tickets assigned to them).
    """
    if role == Role.ADMIN:
        return "all"
    if role == Role.ADVISOR:
        return "assigned"
    return "own"
