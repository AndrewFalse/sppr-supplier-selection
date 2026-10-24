import numpy as np
import pytest

from sppr import ahp


def test_consistent_matrix_has_zero_cr():
    w = np.array([0.5, 0.3, 0.2])
    a = w[:, None] / w[None, :]
    res = ahp.consistency(a)
    assert np.allclose(res["weights"], w)
    assert abs(res["cr"]) < 1e-9
    assert abs(res["lambda_max"] - 3) < 1e-9


def test_saaty_textbook_example():
    # классический пример: λmax ≈ 3.0385, ОС ≈ 0.033
    a = ahp.matrix_from_upper(3, {(0, 1): 3, (0, 2): 5, (1, 2): 2})
    res = ahp.consistency(a)
    assert res["lambda_max"] == pytest.approx(3.0037, abs=1e-3)
    assert res["cr"] < 0.1
    assert res["weights"][0] > res["weights"][1] > res["weights"][2]


def test_geometric_mean_close_to_eigenvector():
    a = ahp.matrix_from_upper(4, {(0, 1): 2, (0, 2): 3, (0, 3): 5, (1, 2): 2, (1, 3): 3, (2, 3): 2})
    w_eig, _ = ahp.priority_vector(a)
    w_gm = ahp.geometric_mean_weights(a)
    assert np.allclose(w_eig, w_gm, atol=0.01)


def test_min_criterion_prefers_lower_value():
    a = ahp.matrix_from_values([100, 200, 400], "min")
    w, _ = ahp.priority_vector(a)
    assert w[0] > w[1] > w[2]
    assert np.allclose(a * a.T, 1)


def test_ratings_matrix_is_reciprocal_and_ordered():
    a = ahp.matrix_from_ratings([5, 3, 1], "max")
    assert a[0, 1] == 5 and a[0, 2] == 9 and a[1, 2] == 5
    assert np.allclose(a * a.T, 1)
    w, _ = ahp.priority_vector(a)
    assert w[0] > w[1] > w[2]
    w_min, _ = ahp.priority_vector(ahp.matrix_from_ratings([5, 3, 1], "min"))
    assert w_min[2] > w_min[1] > w_min[0]


def test_bad_matrix_rejected():
    with pytest.raises(ValueError):
        ahp.check_matrix([[1, 2], [2, 1]])
    with pytest.raises(ValueError):
        ahp.matrix_from_upper(3, {(0, 1): 2})


def test_synthesis_sums_to_one():
    w = [0.6, 0.4]
    p = [[0.7, 0.2], [0.3, 0.8]]
    g = ahp.synthesize(w, p)
    assert g.sum() == pytest.approx(1.0)
