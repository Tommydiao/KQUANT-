from kquant.options_opening_trend_coverage import factor_grade,complete_s0_factor,complete_numeric_factor


def test_partial_object_is_not_complete_s0():
    row={'state':'INCOMPLETE','factor_evidence':{'state':'PARTIAL_PRICE_COMPONENTS',
        'momentum':.8,'close_position':.9,'previous_close':None,'day_open':100,'price':102,
        'momentum_threshold':.5,'close_position_threshold':.75,'prior_boundary':None,'reference':{},
        'checks':{'daily_direction':None,'momentum':True,'close_position':True,'prior_breakout':True}}}
    assert factor_grade(row)=='PARTIAL_PRICE_COMPONENTS' and not complete_s0_factor(row)


def test_full_actual_shape_is_separate_from_trigger():
    factor={'day_open':100,'previous_close':101,'momentum':.8,'close_position':.9,'price':102,
        'momentum_threshold':.5,'close_position_threshold':.75,'prior_boundary':None,'reference':{},
        'auxiliary':{'role':'AUXILIARY_ONLY'},
        'checks':{'daily_direction':True,'momentum':True,'close_position':True,'prior_breakout':False}}
    row={'state':'NO_TRIGGER','factor_evidence':factor}
    assert factor_grade(row)=='FULL' and complete_s0_factor(row)
    row['state']='INCOMPLETE'
    assert factor_grade(row)=='FULL' and not complete_s0_factor(row)


def test_old_boolean_or_empty_object_cannot_fabricate_factor():
    assert factor_grade({'factor_evidence_present':True})=='NONE'
    assert not complete_s0_factor({'state':'NUMERIC_PASS','factor_evidence':{}})
    assert factor_grade({'factor_evidence':{'state':'PARTIAL_PRICE_COMPONENTS'}})=='NONE'


def test_old_pullback_factor_remains_numeric_but_is_not_s0():
    row={'state':'NO_TRIGGER','factor_evidence':dict(opening_high=102,opening_low=100,
        opening_width=2,day_open=100,previous_close=101,vwap=101,price=102,
        trend_bar={'close':102},reference={'previous_close':101})}
    assert complete_numeric_factor(row,momentum=False)
    assert not complete_numeric_factor(row,momentum=True)
