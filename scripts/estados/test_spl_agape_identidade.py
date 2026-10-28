"""Regressões de identidade do texto vinculado ao cadastro SPL/AGAPE."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
