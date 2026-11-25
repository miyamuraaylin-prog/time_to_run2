ROLE_PERMISSIONS = {
    "resumo": {
        "Administrador", "Secretariado Inscrições", "Secretariado Partida",
        "Secretariado Meta", "Consulta",
    },
    "inscricoes": {"Secretariado Inscrições"},
    "alunos": {"Administrador", "Secretariado Inscrições"},
    "partida": {"Secretariado Partida"},
    "meta": {"Secretariado Meta"},
    "classificacoes": {
        "Secretariado Meta", "Consulta", "Secretariado Inscrições",
    },
    "relatorios": {"Consulta", "Secretariado Inscrições"},
    "config": {"Administrador"},
    "responsaveis": {"Administrador"},
}


def pode(user, modulo):
    if not user:
        return False
    perfis = set(user.get("perfis", []))
    if "Administrador" in perfis:
        return True
    return bool(perfis & ROLE_PERMISSIONS.get(modulo, set()))
