import numpy as np
import pytest
from kquant_crypto.hybrid_nested_baseline import inner_choice


def test_fixed_inner_comparison_has_no_outer_inputs():
    x = np.arange(20.,dtype=float).reshape(10,2)
    result = inner_choice(x[:6],np.arange(6.),x[6:],np.arange(6.,10.))
    assert len(result['scores']) == 3
    assert result['runtime_enabled'] is False
    with pytest.raises(ValueError):
        inner_choice(x[:6],np.arange(6.),x[6:],np.array([1,2,3,np.nan]))
