def test_loads_and_lists_species(vocab):
    ids = vocab.species_ids()
    assert "ruby" in ids and "sapphire" in ids and "emerald" in ids
    assert "jadeite" not in ids  # open item — must not be silently resolved


def test_every_species_has_positive_sg_and_a_clarity_system(vocab):
    for sid in vocab.species_ids():
        sp = vocab.species(sid)
        assert sp.sg > 0, sid
        assert sp.clarity_systems, sid
        for system in sp.clarity_systems:
            assert vocab.clarity_grades(system), (sid, system)


def test_ruby_trade_terms_include_pigeons_blood(vocab):
    names = vocab.trade_color_names("ruby")
    assert "Pigeon's Blood" in names
    pigeons = next(t for t in vocab.trade_color_terms("ruby") if t.term == "Pigeon's Blood")
    assert pigeons.gia  # trade term and GIA translation are BOTH stored


def test_sapphire_colors_span_blue_and_fancy(vocab):
    names = vocab.trade_color_names("sapphire")
    assert "Royal Blue" in names
    assert "Padparadscha" in names


def test_clarity_grades_by_system(vocab):
    assert "VS" in vocab.clarity_grades("gia_type_ii")
    assert "VVS1" in vocab.clarity_grades("gia_diamond")
    assert vocab.clarity_grades("gia_type_iii")


def test_every_cut_has_a_shape_factor(vocab):
    assert "round_brilliant" in vocab.cut_ids()
    for cid in vocab.cut_ids():
        assert 0 < vocab.cut(cid).shape_factor < 1, cid


def test_phenomena_registry(vocab):
    assert set(vocab.species("sapphire").allowed_phenomena) == {"asterism_star", "color_change"}
    assert set(vocab.phenomena_ids()) >= {"chatoyancy_cats_eye", "asterism_star", "color_change"}
