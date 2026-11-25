import csv
import html
import io
from datetime import date

from config import APP_TITLE
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


VERDE_ESCURO = "#11663A"


def gerar_csv_classificacao(linhas):
    conteudo = io.StringIO(newline="")
    escritor = csv.writer(conteudo, delimiter=";", lineterminator="\n")
    escritor.writerow(("posicao", "nome", "dorsal", "escalao"))
    for linha in linhas:
        escritor.writerow((
            linha["posicao_geral"], linha["nome"], linha["dorsal"],
            linha["escalao"] or "",
        ))
    return conteudo.getvalue().encode("utf-8-sig")


def gerar_pdf_classificacao(linhas):
    buffer = io.BytesIO()
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "TituloClassificacao", parent=estilos["Title"],
        textColor=colors.HexColor(VERDE_ESCURO), alignment=TA_CENTER,
        spaceAfter=6,
    )
    subtitulo = ParagraphStyle(
        "SubtituloClassificacao", parent=estilos["Normal"],
        textColor=colors.HexColor("#637168"), alignment=TA_CENTER,
        spaceAfter=18,
    )
    celula = ParagraphStyle(
        "CelulaClassificacao", parent=estilos["BodyText"], fontSize=9,
        leading=12,
    )
    cabecalho = ParagraphStyle(
        "CabecalhoClassificacao", parent=celula, textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), rightMargin=36, leftMargin=36,
        topMargin=36, bottomMargin=36, title="Classificação geral",
        author=APP_TITLE,
    )
    dados = [[
        Paragraph("Posição", cabecalho),
        Paragraph("Nome", cabecalho),
        Paragraph("Dorsal", cabecalho),
        Paragraph("Escalão", cabecalho),
    ]]
    for linha in linhas:
        dados.append([
            Paragraph(html.escape(str(linha["posicao_geral"])), celula),
            Paragraph(html.escape(str(linha["nome"])), celula),
            Paragraph(html.escape(str(linha["dorsal"])), celula),
            Paragraph(html.escape(str(linha["escalao"] or "-")), celula),
        ])

    tabela = Table(dados, colWidths=(62, 390, 72, 210), repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(VERDE_ESCURO)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F0F6F1")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7E2DA")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    documento.build([
        Paragraph("Classificação Geral", titulo),
        Paragraph(html.escape(APP_TITLE), subtitulo),
        tabela,
        Spacer(1, 12),
        Paragraph(f"Gerado em {date.today():%d/%m/%Y} · "
                  f"{len(linhas)} participantes", estilos["Normal"]),
    ])
    return buffer.getvalue()
