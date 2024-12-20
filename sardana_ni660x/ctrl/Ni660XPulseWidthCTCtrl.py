from sardana import DataAccess
from sardana.pool.controller import (CounterTimerController, Memorize,
                                     Memorized, Type, Access)

from sardana_ni660x.ctrl.Ni660XCTCtrl import Ni660XCTCtrl
from sardana_ni660x.utils import getPFIName


# The order of inheritance is important. The CounterTimerController
# implements the API methods e.g. StateOne. Their default implementation raises
# the NotImplementedError. The Ni660XCTCtrl implementation must take
# precedence.
class Ni660XPulseWidthCTCtrl(Ni660XCTCtrl, CounterTimerController):
    """This class is the Ni600X counter Sardana CounterTimerController.
    It can work in step and continuous scan mode. """

    BUFFER_ATTR = 'PulseWidthBuffer'
    APP_TYPE = 'CIPulseWidthChan'
    SAMPLE_TIMING_TYPE = 'Implicit'
    CLK_SOURCE = 'inputterminal'

    axis_attributes = dict(Ni660XCTCtrl.axis_attributes)
    axis_attributes.update({
        "inputterminal": {
            Type: str,
            Access: DataAccess.ReadWrite,
            Memorize: Memorized
        },
    })

    def __init__(self, inst, props, *args, **kwargs):
        CounterTimerController.__init__(self, inst, props, *args, **kwargs)
        Ni660XCTCtrl.__init__(self, inst, props, *args, **kwargs)

    def PreStartOne(self, axis, value):
        if (Ni660XCTCtrl.PreStartOne(self, axis, value) and axis != 1):
            channel = self.channels[axis]
            self._log.debug(self.counterName[axis])
            source_terminal = getPFIName(self.counterName[axis],'src')
            channel.write_attribute('SourceTerminal',source_terminal)
        return True
