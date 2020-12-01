import tango

from sardana import DataAccess
from sardana.pool.controller import (CounterTimerController,
                                     Memorize, NotMemorized, Memorized)
from sardana.pool.controller import Type, Access
from sardana_ni660x.ctrl.Ni660XCTCtrl import Ni660XCTCtrl


ReadWrite = DataAccess.ReadWrite


# The order of inheritance is important. The CounterTimerController
# implements the API methods e.g. StateOne. Their default implementation raises
# the NotImplementedError. The Ni660XCTCtrl implementation must take
# precedence.
class Ni660XPositionCTCtrl(Ni660XCTCtrl, CounterTimerController):
    "This class is the Ni600X position capture Sardana CounterTimerController"

    BUFFER_ATTR = 'PositionBuffer'
    QUERY_FILTER = 1
    SAMPLE_TIMING_TYPE = 'SampClk'
    APP_TYPE = 'CIAngEncoderChan'
    CLK_SOURCE = 'sampleclocksource'

    axis_attributes = dict(Ni660XCTCtrl.axis_attributes)
    axis_attributes.update({
        "pulsesPerRevolution": {
            Type: int,
            Access: ReadWrite,
            Memorize: Memorized
        },
        "initialPos": {
            Type: float,
            Access: ReadWrite,
            Memorize: NotMemorized
        },
        "initialPosAttr": {
            Type: str,
            Access: ReadWrite
        },
        "zIndexEnabled": {
            Type: bool,
            Access: ReadWrite,
            Memorize: NotMemorized
        },
        "units": {
            Type: str,
            Access: ReadWrite,
            Memorize: Memorized
        },
        "sign": {
            Type: int,
            Access: ReadWrite,
        }
    })

    direct_attributes = Ni660XCTCtrl.direct_attributes + (
        'units', 'pulsesperrevolution', 'zindexenabled')

    def __init__(self, inst, props, *args, **kwargs):
        CounterTimerController.__init__(self, inst, props, *args, **kwargs)
        Ni660XCTCtrl.__init__(self, inst, props, *args, **kwargs)

    def AddDevice(self, axis):
        Ni660XCTCtrl.AddDevice(self, axis)
        if axis != 1:
            #readount ot 60000 buffer takes aprox 10 seconds
            self.channels[axis].set_timeout_millis(120000)
            self.attributes[axis]['sign'] = 1
            self.attributes[axis]['initialpos'] = None
            self.attributes[axis]['initialposattr'] = ""
            self.attributes[axis]['initialposattrproxy'] = None
            self.attributes[axis]['initialposvalue'] = 0

    def PreStartOne(self, axis, value):
        if Ni660XCTCtrl.PreStartOne(self, axis, value) and axis != 1:
            initial_pos_value = self._get_initial_pos_value(axis)
            self.attributes[axis]["initialposvalue"] = initial_pos_value
        return True

    def _get_initial_pos_value(self, axis):
        axis_attr = self.attributes[axis]
        initial_pos_value = axis_attr.get('initialpos')
        if initial_pos_value is None:
            initial_pos_value = 0
            proxy = axis_attr['initialposattrproxy']
            attr_name = axis_attr['initialposattr']
            if proxy is None and attr_name:
                proxy = tango.AttributeProxy(attr_name)
                # save in cache to avoid recreating AttributeProxy
                axis_attr['initialposattrproxy'] = proxy
            if proxy is not None:
                try:
                    initial_pos_value = float(proxy.read().value)
                except ValueError:
                    msg = "initialPosAttr (%s) is not float" % attr_name
                    raise Exception(msg)
        return initial_pos_value

    def _calculate(self, axis, data, index):
        data = data[index:]
        if self.attributes[axis]["sign"] == -1:
            data = data * -1
        data = data + self.attributes[axis]["initialposvalue"]
        return data

    def SetAxisExtraPar(self, axis, name, value):
        super().SetAxisExtraPar(axis, name, value)
        if name.lower() == 'initialposattr':
            self.attributes['axis']['initialposattrproxy'] = None
