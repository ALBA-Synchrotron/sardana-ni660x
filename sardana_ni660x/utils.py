from enum import Enum

import taurus
from taurus.core.util import SafeEvaluator

class IdleState(Enum):
    LOW = "Low"
    HIGH = "High"
    NOT_SET = "NotSet"

CONNECTTERMS_DOC = ('String with dictionary form. Keys are Ni660X Tango' 
                    ' device names. Each value is a list of tuples.'
                    ' Each tuple has: (source termninal, destination terminal'
                    ' , polarity configuration)')

NI6602_PFI = {
    "ctr0": {"src": "PFI39", "gate": "PFI38", "out": "PFI36", "aux": "PFI37"},
    "ctr1": {"src": "PFI35", "gate": "PFI34", "out": "PFI32", "aux": "PFI33"},
    "ctr2": {"src": "PFI31", "gate": "PFI30", "out": "PFI28", "aux": "PFI29"},
    "ctr3": {"src": "PFI27", "gate": "PFI26", "out": "PFI24", "aux": "PFI25"},
    "ctr4": {"src": "PFI23", "gate": "PFI22", "out": "PFI20", "aux": "PFI21"},
    "ctr5": {"src": "PFI19", "gate": "PFI18", "out": "PFI16", "aux": "PFI17"},
    "ctr6": {"src": "PFI15", "gate": "PFI14", "out": "PFI12", "aux": "PFI13"},
    "ctr7": {"src": "PFI11", "gate": "PFI10", "out": "PFI8",  "aux": "PFI9"}}

def getPFIName(counterName, signal):
    """ Method to get the PFI signal name for each counter, e.g.:/Dev1/ctr1 """
    counter = counterName[-4:].lower()
    pfi = NI6602_PFI[counter][signal.lower()]
    return counterName[:-4] + pfi

def getPFINameFromFriendlyWords(counter):
    """
    Method to check/extract the PFI from a counter name
    Can be used with /dev1/PFI34 format or /dev1/ctr1/gate
    """
    # Convert from friendly words
    if 'rtsi'in counter.lower():
        pass
    elif not 'pfi' in counter.lower():
        term = counter.rsplit('/',1)
        ctr = term[0]
        signal = term[1]
        counter = getPFIName(ctr, signal)
    return counter

class ConnectTerms:
    def __init__(self, connect_terms):
        self.connectTerms = connect_terms
        self.sev = SafeEvaluator()
        self.cards = {}
        self.card_configured = {}
        cards = self.sev.eval(self.connectTerms)
        for card_dev_name in cards.keys():
            value = cards[card_dev_name]
            card_dev = taurus.Device(card_dev_name)
            self.cards[card_dev] = value
            self.card_configured[card_dev] = False

    def apply_connect_terms(self):
        for card_dev in self.card_configured.keys():
            for device_tuple in self.cards[card_dev]:
                src_terminal = device_tuple[0]
                #Check if is defined as a friendly words
                src_terminal = getPFINameFromFriendlyWords(src_terminal)
                dest_terminal = device_tuple[1]
                dest_terminal = getPFINameFromFriendlyWords(dest_terminal)
                polarity = device_tuple[2]
                card_dev.ConnectTerms([src_terminal,
                                       dest_terminal,
                                       polarity])
            self.card_configured[card_dev] = True

    def delete_cards(self):
        cards = self.sev.eval(self.connectTerms)
        for card_dev_name in cards.keys():
            card_dev = taurus.Device(card_dev_name)
            del self.cards[card_dev]
            del self.card_configured[card_dev]

