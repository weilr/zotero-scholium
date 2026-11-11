"""The translation check by the comment's script. A comment in Chinese, Japanese or Korean is checked as before (its output
on golden/translation_cjk.json is frozen): every Latin word and number in it must come from the sentence. A comment in
Cyrillic is checked the same way, with its number words and decimal comma read. A comment in a Latin-script language (de,
fr, es, pt, or en for a paper in another language) is checked for numbers, read with the language's number words and its
comma or period, and for term-like words only (acronyms, CamelCase, words with digits or Greek letters): its ordinary
words, umlauts and accents included, are its own."""
import json
from pathlib import Path

import pytest

from zotero_scholium import cli

GOLDEN = Path(__file__).with_name("golden")


def reasons(source, comment):
    return [r for w in cli.check_translations([{"type": "highlight", "pageLabel": "1", "text": source, "comment": comment}])
            for r in w["reasons"]]


def test_cjk_comments_are_checked_as_before():
    for text, comment, before in json.loads((GOLDEN / "translation_cjk.json").read_text(encoding="utf8")):
        assert cli.check_translations([{"type": "highlight", "pageLabel": "1", "text": text, "comment": comment}]) == before, comment


def test_the_german_comments_of_a_real_run_are_not_flagged():
    """The 14 comments of a German annotation of the DPO paper, each a faithful translation."""
    pairs = json.loads((GOLDEN / "translation_de_dpo.json").read_text(encoding="utf8"))
    assert len(pairs) == 14
    assert [(comment[:40], reasons(text, comment)) for text, comment in pairs if reasons(text, comment)] == []


@pytest.mark.parametrize("source, comment", [
    # numbers with the language's words for thousand, million and billion, and its decimal comma and grouping
    ("We use language models with up to 6B parameters.", "Wir nutzen Sprachmodelle mit bis zu 6 Milliarden Parametern."),
    ("The dataset has 1.5M examples.", "Der Datensatz hat 1,5 Mio. Beispiele."),
    ("The dataset has 1.5M examples.", "Der Datensatz hat 1.500.000 Beispiele."),
    ("We train for 10K steps.", "Wir trainieren 10 Tsd. Schritte lang."),
    ("The error is 3.57%.", "Der Fehler beträgt 3,57 %."),
    ("We use models with up to 6B parameters.", "Nous utilisons des modèles jusqu'à 6 milliards de paramètres."),
    ("It has 1,500,000 images.", "Il contient 1 500 000 images."),
    ("We use models with up to 6B parameters.", "Usamos modelos de hasta 6 mil millones de parámetros."),
    ("The dataset has 1.5M examples.", "El conjunto tiene 1,5 millones de ejemplos."),
    ("We use models with up to 6B parameters.", "Usamos modelos com até 6 bilhões de parâmetros."),
    ("We use models with up to 6B parameters.", "Usamos modelos com até 6 mil milhões de parâmetros."),
    # an English comment on a German paper
    ("Wir nutzen Sprachmodelle mit bis zu 6 Mrd. Parametern und 1,5 Mio. Beispielen.",
     "We use language models with up to 6B parameters and 1.5M examples."),
    # names, acronyms and symbols that the sentence has
    ("Reward Modelling Phase: pairs of answers (y1, y2) ∼πSFT(y | x) from PbRL.",
     "Belohnungsphase: Paare von Antworten (y1, y2) ∼ πSFT(y | x) aus PbRL."),
])
def test_a_faithful_comment_in_a_latin_script_language_is_not_flagged(source, comment):
    assert reasons(source, comment) == []


@pytest.mark.parametrize("source, comment, quoted", [
    ("We use models with up to 6B parameters.", "Wir nutzen Modelle mit bis zu 60 Mrd. Parametern.", "60 Mrd."),
    ("The dataset has 1.5M examples.", "Der Datensatz hat 15 Mio. Beispiele.", "15 Mio."),
    ("The error is 3.57%.", "Der Fehler beträgt 35,7 %.", "35,7 %"),
    ("We compare DPO with RLHF.", "Wir vergleichen DPO mit PPO.", "ppo"),
    ("We compare DPO with RLHF.", "Wir vergleichen DPO mit RLHF auf GPT4o.", "gpt4o"),
    ("We use models with up to 6B parameters.", "Nous utilisons des modèles jusqu'à 60 milliards de paramètres.", "60 milliards"),
    ("Wir nutzen Sprachmodelle mit bis zu 6 Mrd. Parametern.", "We use language models with up to 60B parameters.", "60B"),
])
def test_a_changed_number_or_an_added_term_is_flagged_as_written(source, comment, quoted):
    [reason] = reasons(source, comment)
    assert reason.startswith("terms or numbers not present") and quoted in reason


@pytest.mark.parametrize("source, comment, flagged", [
    ("We use language models with up to 6B parameters.", "Мы используем языковые модели до 6 млрд параметров.", None),
    ("The dataset has 1.5M examples.", "Набор данных содержит 1,5 млн примеров.", None),
    ("We use language models with up to 6B parameters.", "Мы используем языковые модели до 60 млрд параметров.", "60 млрд"),
    # a Latin word in a Russian comment is a term, as in a Chinese one
    ("We compare DPO with RLHF.", "Мы сравниваем DPO с PPO.", "ppo"),
    ("We compare DPO with RLHF.", "Мы сравниваем DPO и RLHF.", None),
])
def test_a_russian_comment_is_read_with_its_numbers_and_its_latin_terms(source, comment, flagged):
    found = reasons(source, comment)
    assert (found == []) if flagged is None else (len(found) == 1 and flagged in found[0])


@pytest.mark.parametrize("source, comment, quoted", [
    # a number off by a thousand: read the German way the comment says 1.5, the English way the sentence says 1500
    ("We train on 1,500 images per class.", "Wir trainieren auf 1,5 Bildern pro Klasse.", "1,5"),
    ("We train on 1,500 images per class.", "Wir trainieren auf 1.5 Bildern pro Klasse.", "1.5"),
    # a German paper read with its own convention, an English comment read with English's
    ("Wir trainieren auf 1,5 Mio. Bildern.", "We train on 1,500 images.", "1,500"),
])
def test_each_side_is_read_with_its_own_convention(source, comment, quoted):
    [reason] = reasons(source, comment)
    assert quoted in reason


def test_the_chinese_counterpart_is_flagged_as_before():
    assert reasons("We train on 1,500 images per class.", "我们在每类 1.5 张图像上训练。")
