from news_utils.prefilter import MaterialityPrefilter


def test_prefilter_merger_high_amount_scores_high():
    pf = MaterialityPrefilter(model_path=None)  # no model; heuristics only
    title = "MegaCorp to acquire StartupX in $2.5B all-cash deal"
    res = pf.score(title)
    assert res.score >= 0.7, res


def test_prefilter_rumor_penalty():
    pf = MaterialityPrefilter(model_path=None)
    title = "Company Y reportedly considering acquisition of Company Z for $50M"
    res = pf.score(title)
    assert res.score < 0.7, res


def test_prefilter_regulator_boost():
    pf = MaterialityPrefilter(model_path=None)
    title = "FDA approves Drug ABC for rare disease"
    res = pf.score(title, source_domain="fda.gov")
    assert res.score >= 0.7, res
