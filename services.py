from auth import verificar
from db import execute, query


def autenticar_utilizador(username, password):
    utilizador = query(
        """SELECT u.id, u.nome, u.username, u.password_hash, u.ativo
           FROM utilizadores u WHERE u.username=%s""",
        (username,),
        one=True,
    )
    if not utilizador or not verificar(password, utilizador["password_hash"]):
        return "invalid", None
    if not utilizador["ativo"]:
        return "inactive", None

    perfis = [
        perfil["nome"] for perfil in query(
            """SELECT p.nome FROM utilizador_perfil up
               JOIN perfis p ON p.id=up.perfil_id
               WHERE up.utilizador_id=%s""",
            (utilizador["id"],),
        )
    ]
    return "ok", {
        "id": utilizador["id"],
        "nome": utilizador["nome"],
        "username": utilizador["username"],
        "perfis": perfis,
    }


def obter_dados_area_aluno(username):
    aluno = query(
        """SELECT a.id, a.numero_aluno, a.nome, a.ano_letivo,
                  t.codigo AS turma_codigo, t.nome AS turma_nome
           FROM alunos a
           JOIN turmas t ON t.id=a.turma_id
           WHERE a.numero_aluno=%s
           ORDER BY a.ano_letivo DESC, a.id DESC
           LIMIT 1""",
        (username,),
        one=True,
    )
    if not aluno:
        return None, []

    inscricoes = query(
        """SELECT p.nome AS prova_nome, p.ano, p.data, p.local,
                  i.dorsal, i.estado, e.nome AS escalao,
                  ci.posicao_geral, ci.posicao_escalao,
                  ci.posicao_genero, ci.apurado,
                  c.ordem AS ordem_chegada
           FROM inscricoes i
           JOIN alunos a ON a.id=i.aluno_id
           JOIN provas p ON p.id=i.prova_id
           LEFT JOIN escaloes e ON e.id=i.escalao_id
           LEFT JOIN classificacoes_individuais ci
                  ON ci.prova_id=i.prova_id AND ci.inscricao_id=i.id
           LEFT JOIN chegadas c
                  ON c.prova_id=i.prova_id AND c.inscricao_id=i.id
           WHERE a.numero_aluno=%s
           ORDER BY p.ano DESC, p.id DESC""",
        (username,),
    )
    return aluno, inscricoes


def calcular_classificacoes(prova_id):
    rows = query(
        """SELECT c.ordem, i.id AS inscricao_id, i.escalao_id, i.indicador_da,
                  a.genero, a.turma_id
           FROM chegadas c
           JOIN inscricoes i ON i.id=c.inscricao_id
           JOIN alunos a ON a.id=i.aluno_id
           WHERE c.prova_id=%s
             AND NOT EXISTS (
                 SELECT 1 FROM ocorrencias o
                 WHERE o.prova_id=c.prova_id AND o.inscricao_id=i.id
             )
           ORDER BY c.ordem""",
        (prova_id,),
    )

    execute("DELETE FROM classificacoes_individuais WHERE prova_id=%s", (prova_id,))
    execute("DELETE FROM classificacoes_coletivas WHERE prova_id=%s", (prova_id,))

    pos_geral = 0
    pos_escalao = {}
    pos_genero = {}
    pos_desporto_adaptado = {}
    for row in rows:
        pos_geral += 1
        escalao_id = row["escalao_id"]
        chave_genero = (escalao_id, row["genero"])
        pos_escalao[escalao_id] = pos_escalao.get(escalao_id, 0) + 1
        pos_genero[chave_genero] = pos_genero.get(chave_genero, 0) + 1
        if row["indicador_da"]:
            pos_desporto_adaptado[escalao_id] = (
                pos_desporto_adaptado.get(escalao_id, 0) + 1
            )
        execute(
            """INSERT INTO classificacoes_individuais
               (prova_id, inscricao_id, posicao_geral, posicao_escalao,
                posicao_genero, posicao_da, apurado)
               VALUES (%s,%s,%s,%s,%s,%s,0)""",
            (
                prova_id, row["inscricao_id"], pos_geral,
                pos_escalao[escalao_id], pos_genero[chave_genero],
                pos_desporto_adaptado.get(escalao_id)
                if row["indicador_da"] else None,
            ),
        )

    for regra in query(
        "SELECT escalao_id, indicador_da, num_apurados FROM regras_apuramento"
    ):
        if regra["num_apurados"] <= 0:
            continue
        selecionados = query(
            """SELECT ci.id FROM classificacoes_individuais ci
               JOIN inscricoes i ON i.id=ci.inscricao_id
               WHERE ci.prova_id=%s AND i.escalao_id=%s
                 AND i.indicador_da=%s
               ORDER BY ci.posicao_escalao LIMIT %s""",
            (
                prova_id, regra["escalao_id"], regra["indicador_da"],
                regra["num_apurados"],
            ),
        )
        for row in selecionados:
            execute(
                "UPDATE classificacoes_individuais SET apurado=1 WHERE id=%s",
                (row["id"],),
            )

    pontos_por_turma = {}
    for row in rows:
        pontos_por_turma.setdefault(row["turma_id"], []).append(row["ordem"])
    for turma_id, ordens in pontos_por_turma.items():
        melhores = sorted(ordens)[:4]
        if len(melhores) == 4:
            execute(
                """INSERT INTO classificacoes_coletivas
                   (prova_id, turma_id, pontos) VALUES (%s,%s,%s)""",
                (prova_id, turma_id, sum(melhores)),
            )

    coletivas = query(
        """SELECT id FROM classificacoes_coletivas
           WHERE prova_id=%s ORDER BY pontos""",
        (prova_id,),
    )
    for posicao, row in enumerate(coletivas, 1):
        execute(
            "UPDATE classificacoes_coletivas SET posicao=%s WHERE id=%s",
            (posicao, row["id"]),
        )
