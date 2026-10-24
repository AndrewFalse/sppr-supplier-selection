"""Метод анализа иерархий (АНР, Analytic Hierarchy Process).

Функции:
- priority_vector  - вектор приоритетов по главному собственному вектору матрицы;
- consistency      - индекс согласованности (ИС) и отношение согласованности (ОС);
- matrix_from_upper - матрица парных сравнений из верхнего треугольника суждений;
- matrix_from_values / matrix_from_ratings - матрицы сравнения альтернатив по данным;
- synthesize       - глобальные приоритеты альтернатив.
"""
import numpy as np

# Случайный индекс (СИ) Саати для матриц порядка n
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

SAATY_MIN, SAATY_MAX = 1 / 9, 9


def check_matrix(a):
    a = np.asarray(a, dtype=float)
    n = a.shape[0]
    if a.shape != (n, n):
        raise ValueError("матрица должна быть квадратной")
    if np.any(a <= 0):
        raise ValueError("элементы матрицы должны быть положительными")
    if not np.allclose(np.diag(a), 1.0):
        raise ValueError("на диагонали должны стоять единицы")
    if not np.allclose(a * a.T, 1.0, atol=1e-6):
        raise ValueError("матрица должна быть обратносимметричной: a_ji = 1 / a_ij")
    return a


def priority_vector(a):
    """Главный собственный вектор, нормированный к сумме 1, и λmax."""
    a = check_matrix(a)
    values, vectors = np.linalg.eig(a)
    k = int(np.argmax(values.real))
    lam = float(values[k].real)
    w = np.abs(vectors[:, k].real)
    return w / w.sum(), lam


def geometric_mean_weights(a):
    """Приближённый способ (как в Excel): среднее геометрическое строк."""
    a = check_matrix(a)
    g = np.prod(a, axis=1) ** (1 / a.shape[0])
    return g / g.sum()


def consistency(a):
    """Возвращает словарь: λmax, ИС = (λmax - n)/(n - 1), СИ, ОС = ИС / СИ."""
    a = check_matrix(a)
    n = a.shape[0]
    w, lam = priority_vector(a)
    if n <= 2:
        return {"n": n, "lambda_max": float(n), "ci": 0.0, "ri": 0.0, "cr": 0.0, "weights": w}
    ci = (lam - n) / (n - 1)
    ri = RANDOM_INDEX[n]
    return {"n": n, "lambda_max": lam, "ci": ci, "ri": ri, "cr": ci / ri, "weights": w}


def matrix_from_upper(n, judgments):
    """judgments: {(i, j): значение} для i < j (индексы с нуля), шкала Саати 1/9..9."""
    a = np.ones((n, n))
    for (i, j), v in judgments.items():
        if not i < j:
            raise ValueError(f"ожидается i < j, получено {(i, j)}")
        a[i, j] = v
        a[j, i] = 1 / v
    missing = [(i, j) for i in range(n) for j in range(i + 1, n) if (i, j) not in judgments]
    if missing:
        raise ValueError(f"не заданы суждения для пар {missing}")
    return a


def matrix_from_values(values, direction):
    """Сравнение по числовому критерию: a_ij = x_i / x_j (max) или x_j / x_i (min),
    ограничено шкалой Саати [1/9; 9]."""
    x = np.asarray(values, dtype=float)
    if np.any(x <= 0):
        raise ValueError("значения числового критерия должны быть положительными")
    ratio = x[:, None] / x[None, :] if direction == "max" else x[None, :] / x[:, None]
    return np.clip(ratio, SAATY_MIN, SAATY_MAX)


def matrix_from_ratings(ratings, direction):
    """Сравнение по оценкам 1-5: разница d переводится в шкалу Саати 1, 3, 5, 7, 9
    (a_ij = 1 + 2d при d >= 0, иначе 1 / (1 - 2d)). Для min-критерия разница берётся наоборот."""
    r = np.asarray(ratings, dtype=float)
    d = r[:, None] - r[None, :]
    if direction == "min":
        d = -d
    return np.where(d >= 0, 1 + 2 * d, 1 / (1 - 2 * d))


def synthesize(criteria_weights, local_priorities):
    """Глобальный приоритет альтернативы = Σ_k w_k · p_k(a).
    local_priorities: матрица (число альтернатив × число критериев)."""
    w = np.asarray(criteria_weights, dtype=float)
    p = np.asarray(local_priorities, dtype=float)
    return p @ w
