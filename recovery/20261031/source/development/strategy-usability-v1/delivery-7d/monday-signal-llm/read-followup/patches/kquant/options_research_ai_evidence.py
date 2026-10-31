"""Pure shared packet identity; read projections do not import paid execution."""
from copy import deepcopy
from . import options_one_minute as common

MODELS={'SOL':'gpt-6.1-sol','ASTRA':'gpt-6-astra'}


def evidence_packet(event):
    fields=('event_id','evaluation_id','symbol','right','session','calculation_bar_end',
        'deadline_at','runtime_inputs','state','conditions','bar_evidence','amplitude',
        'structure_line','entry_range','reference_contract','option_cost','event_coverage',
        'research_only','qualified_signal','input_revision')
    packet={key:deepcopy(event[key]) for key in fields if key in event}
    packet['source_refs']={name:common.digest(packet[name]) for name in
        ('bar_evidence','reference_contract','option_cost','event_coverage') if name in packet}
    packet['research_only']=True
    packet['qualified_signal']=False
    return packet
