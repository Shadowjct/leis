"""Regressoes de fonte, identidade e anti-duplicacao do complemento ALBA."""
import datetime as dt
import unittest
from unittest.mock import patch

import ingestao_ba_alba as alba


class IngestaoBahiaAlbaTest(unittest.TestCase):
    def test_sumario_identifica_materia_sem_inferir_numero(self):
        html = '''<ul><li><a class="linkMateria" identificador="1241249">
          #1149166 - LEI 15.117_2026</a></li>
          <li><a class="linkMateria" identificador="1241255">
          #1149171 - LEI 15.121_2026</a></li></ul>'''
        obj = alba.Summary()
        obj.feed(html)
        self.assertEqual(
            {alba.law_from_label(label, 2026): ident for ident, label in obj.items},
            {15117: "1241249", 15121: "1241255"},
        )

    def test_nao_inferir_numero_de_edicao_ou_ano_divergente(self):
        self.assertIsNone(alba.law_from_label("#123 - AVISO 15.117_2026", 2026))
        self.assertIsNone(alba.law_from_label("#123 - LEI 15.117_2025", 2026))

    def test_nomes_legados_anti_duplicacao(self):
        self.assertEqual(alba.norm_number("lei-no-15071-de-08-de-janeiro-de-2026.md"), 15071)
        self.assertEqual(alba.norm_number("lei-n-o-15112-de-28-de-janeiro-de-2026.md"), 15112)
        self.assertEqual(alba.norm_number("lei-ordinaria-15117-2026-alba-1241249.md"), 15117)
        self.assertIsNone(alba.norm_number("manifesto.md"))

    def test_diretorio_existente_numeros_e_nomes_atipicos(self):
        normal = [
            {"type": "file", "name": "lei-no-15071-de-08-de-janeiro-de-2026.md"},
            {"type": "file", "name": "lei-ordinaria-15117-2026-alba-1241249.md"},
        ]
        with patch.object(alba, "gh", return_value=(200, normal)):
            self.assertEqual(alba.existing_numbers(2026, ""), {15071, 15117})
        with patch.object(alba, "gh", return_value=(200, normal + [{"type": "file", "name": "invalido.md"}])):
            with self.assertRaisesRegex(RuntimeError, "fora do padrao"):
                alba.existing_numbers(2026, "")

    def test_conversao_texto_word_com_ordinais(self):
        html = """<html><head><style>Art. 999</style></head><body>
        <p>LEI Nº 15.117, DE 28 DE JANEIRO DE 2026</p>
        <p>Institui medidas oficiais para garantia do direito de acesso à informação.</p>
        <p>A PRESIDENTE DA ASSEMBLEIA LEGISLATIVA DO ESTADO DA BAHIA promulga:</p>
        <p>Art. 1º - Fica criado um mecanismo para garantir publicidade dos atos.</p>
        <p>§ 1º O órgão competente providenciará os dados necessários.</p>
        <p>Art. 2° - Esta Lei entra em vigor na data da publicação.</p>
        <p>GABINETE DA PRESIDÊNCIA DA ASSEMBLEIA LEGISLATIVA DO ESTADO DA BAHIA.</p>
        <p>Deputada PRESIDENTE FICTÍCIA</p><p>Presidente</p></body></html>"""
        date, ementa, body, articles = alba.extract_law(html.encode("utf-8"), 15117, dt.date(2026, 1, 29))
        self.assertEqual(date, dt.date(2026, 1, 28))
        self.assertEqual(articles, 2)
        self.assertIn("§ 1º", body)
        self.assertNotIn("Art. 999", body)
        self.assertIn("direito de acesso", ementa)

    def test_retencao_por_tabela_e_ausencia_de_artigo(self):
        html = """<body><p>LEI Nº 15.117, DE 28 DE JANEIRO DE 2026</p>
        <p>Ementa de uma lei fictícia com parâmetros de contagem.</p>
        <p>A PRESIDENTE DA ASSEMBLEIA LEGISLATIVA DO ESTADO DA BAHIA promulga.</p>
        <p>Art. 1º - Texto extenso de abertura da norma, com mais palavras para validação.</p>
        <table><tr><td>ANEXO OBRIGATÓRIO</td></tr></table>
        <p>Presidente</p></body>"""
        with self.assertRaisesRegex(ValueError, "Layout nao linear"):
            alba.extract_law(html.encode("utf-8"), 15117, dt.date(2026, 1, 29))

    def test_numero_nao_coincide_rejeitar(self):
        self.assertEqual(alba.text_number("LEI Nº 15.117, DE 28 DE JANEIRO DE 2026"), 15117)
        self.assertNotEqual(alba.text_number("LEI Nº 15.117, DE 28 DE JANEIRO DE 2026"), 15121)

    def test_data_nao_confundir_publicacao_com_promulgacao(self):
        self.assertEqual(alba.extract_date("LEI Nº 15.117, DE 28 DE JANEIRO DE 2026"),
                         dt.date(2026, 1, 28))


if __name__ == "__main__":
    unittest.main()
