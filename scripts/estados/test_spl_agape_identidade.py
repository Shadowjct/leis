"""Regressões de identidade do texto vinculado ao cadastro SPL/AGAPE."""
import unittest
from unittest import mock

import spl_agape

from spl_agape import divergencia_ano_fecho


class IdentidadeFechoTest(unittest.TestCase):
    def test_rejeita_corpo_de_1947_em_cadastro_de_1967(self):
        texto = ("**LEI Nº 4**\nArt. 1º As sessões da Assembleia...\n"
                 "Vitória, em 15 de outubro de 1947.\nWALDEMAR MENDES")
        self.assertIn("1947", divergencia_ano_fecho(texto, "1967"))

    def test_aceita_fecho_do_ano_cadastrado(self):
        texto = ("**LEI DELEGADA Nº 4**\nArt. 1º ...\n"
                 "Palácio Anchieta, em Vitória, 09 de outubro de 1967.")
        self.assertIsNone(divergencia_ano_fecho(texto, "1967"))

    def test_nao_confunde_citacao_de_lei_antiga_com_fecho(self):
        texto = ("Na forma da Lei 62, de 1936.\nArt. 1º ...\n"
                 "Vitória, em 9 de outubro de 1967.")
        self.assertIsNone(divergencia_ano_fecho(texto, "1967"))

    def test_tolera_virada_de_ano_e_ausencia_de_fecho(self):
        self.assertIsNone(divergencia_ano_fecho("Vitória, 31 de dezembro de 1968.", "1967"))
        self.assertIsNone(divergencia_ano_fecho("Art. 1º ...", "1967"))
        self.assertIsNone(divergencia_ano_fecho("Vitória, 15 de outubro de 1947.", "sem-ano"))


    def test_rejeita_sem_gravar_texto_historico_trocado(self):
        item = {"tipo": "8", "Numero": "4", "Ano": "1967", "cod": "24455", "Data": "13/10/1967"}
        corpo = ("ESTADO DO ESPÍRITO SANTO\n**LEI Nº 4**\n"
                 "Art. 1º As sessões da Assembleia Legislativa principiarão às 14 horas.\n"
                 "Vitória, em 15 de outubro de 1947.\n")
        with (
            mock.patch.object(spl_agape.os.path, "exists", return_value=False),
            mock.patch.object(spl_agape, "caminhos", return_value=("falso.md", "fonte.html")),
            mock.patch.object(spl_agape, "localizar_texto",
                              return_value=("https://exemplo.invalid/LO0004.html", b"html", "text/html")),
            mock.patch.object(spl_agape, "html_para_md", return_value=corpo),
            mock.patch.object(spl_agape, "gravar") as gravar,
        ):
            status, detalhe = spl_agape.processar(item)
        self.assertEqual(status, "sem_texto")
        self.assertEqual(detalhe["cod"], "24455")
        self.assertIn("1947", detalhe["motivo"])
        gravar.assert_not_called()

    def test_grava_texto_com_fecho_compativel(self):
        item = {"tipo": "8", "Numero": "4", "Ano": "1967", "cod": "24455", "Data": "13/10/1967"}
        corpo = ("ESTADO DO ESPÍRITO SANTO\n**LEI DELEGADA Nº 4**\n"
                 "Art. 1º Estabelece a estrutura e define a competência dos órgãos estaduais.\n"
                 "Vitória, em 13 de outubro de 1967.\n")
        with (
            mock.patch.object(spl_agape.os.path, "exists", return_value=False),
            mock.patch.object(spl_agape, "caminhos", return_value=("falso.md", "fonte.html")),
            mock.patch.object(spl_agape, "localizar_texto",
                              return_value=("https://exemplo.invalid/LD41967.html", b"html", "text/html")),
            mock.patch.object(spl_agape, "html_para_md", return_value=corpo),
            mock.patch.object(spl_agape, "gravar") as gravar,
        ):
            status, detalhe = spl_agape.processar(item)
        self.assertEqual(status, "ok")
        self.assertIsNone(detalhe)
        gravar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
