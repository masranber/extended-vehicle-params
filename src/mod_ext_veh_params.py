# Need to clean up imports, most of these were for testing and no longer needed
import BigWorld, json, os, types, sys
from collections import OrderedDict
from itertools import chain
import traceback
from math import radians
from gui.impl import backport
from gui.shared.items_parameters.params import VehicleParams
import gui.shared.items_parameters.params_helper
import gui.shared.items_parameters.comparator
from gui.shared.items_parameters.comparator import PARAM_STATE
import gui.shared.items_parameters.formatters
import gui.shared.items_parameters
#from account_helpers.AccountSettings import DEFAULT_VALUES
from gui.Scaleform.daapi.view.lobby.hangar.VehicleParameters import VehicleParameters, _VehParamsDataProvider
from account_helpers.AccountSettings import AccountSettings
from gui.Scaleform.locale.MENU import MENU
from gui.Scaleform.locale.TOOLTIPS import TOOLTIPS

import inspect

from soft_exception import SoftException

import gui.shared.items_parameters.params_cache
from gui.mods import custom_xml_reader
from gui.mods.patch_tools import inject, hook

from items import tankmen, vehicles
from gui.shared.gui_items.Tankman import TankmanSkill
from gui.shared.gui_items.artefacts import BattleBooster

from gui.Scaleform.locale.MENU import MENU

# parameter section name
#     new parameter:
#           param: parameterID
#           afterParam: order of param list in garage
# Adds a custom parameter to the parameter section (Firepower, Survivability, Mobility, Camo, Spotting)
# after the specified parameter ()


# Things needed to add a custom parameter:
# 1) Create a CustomVehicleParam object and add it to CUSTOM_PARAMS under the desired category
# 2) Create a function in the calculator with the following constraints:
#        - decorate with @inject(VehicleParams, [paramID goes here], is_property=True) to inject the method into the game code
#        - takes 1 parameter 'self', this references the object corresponding to the current vehicle
#        - returns the parameter value calculated for the current vehicle setup
# 3) Add localization strings for the name and description as displayed in the garage to custom.po
#        - the game uses python's gettext l18n module to load localized strings
# 4) Compile custom.po into custom.mo (POEdit works) and add it to lc_messages
#        - unfortunately the human readable .po files don't work so manually compiling is required
# 5) (Optional) add possible bonuses to extended_params_bonuses.xml
# 6) (Optional) compile xml into bigworld encrypted format
# 7) (Optional) add small and big icons with filename '[paramID].jpg'


class DisplayFormat:
    FLOAT = 'float'
    INTEGER = 'int'
    STRING = 'str'
    
    def __init__(self, numFormat=FLOAT, precision=2, backwards=False):
        self.numFormat = numFormat

'''
    Identifies a custom vehicle parameter and its display settings

    paramID: str - id of the parameter you want to add. This can be any name, however it must be consistent with function name
    afterParamID: str - id of the parameter you want custom parameter to appear after in the garage (order of the param list in the garage)
                        not setting this will insert param at the very top of the category
    backwards: bool - true if lower parameter value is better (green vs red text in the garage)
'''
class CustomVehicleParam:

    def __init__(self, paramID, afterParamID=None, backwards=False):
        self.paramID = paramID
        self.afterParamID = afterParamID
        self.backwards = backwards

class CustomParamCategory:

    def __init__(self, paramID, afterParamID=None):
        self.paramID = paramID
        self.afterParamID = afterParamID


gui.shared.items_parameters.params_helper.PARAMS_GROUPS

#
CUSTOM_PARAM_CATEGORIES = [CustomParamCategory(paramID='relativeExtended', afterParamID='relativeVisibility'),
                           CustomParamCategory(paramID='relativeOverall')
                          ]

# Define custom parameters here
CUSTOM_PARAMS = {
        'relativePower':    [ CustomVehicleParam(paramID='dispersionPenaltyMoving', afterParamID='shotDispersionAngle', backwards=True),
                              CustomVehicleParam(paramID='dispersionPenaltyVehTraverse', afterParamID='dispersionPenaltyMoving', backwards=True),
                              CustomVehicleParam(paramID='dispersionPenaltyGunTraverse', afterParamID='dispersionPenaltyVehTraverse', backwards=True)
                            ],
        'relativeMobility': [ CustomVehicleParam(paramID='cruisingSpeed', afterParamID='turboshaftSpeedModeSpeed', backwards=False),
                              CustomVehicleParam(paramID='terrainResistance', afterParamID='chassisRotationSpeed', backwards=True),
                              CustomVehicleParam(paramID='rollingFriction', afterParamID='terrainResistance', backwards=True),
                              CustomVehicleParam(paramID='engineMaxTorque', afterParamID='enginePower', backwards=False),
                              CustomVehicleParam(paramID='engineMaxRpm', afterParamID='engineMaxTorque', backwards=False)
                            ],
        'relativeExtended': [ CustomVehicleParam(paramID='premiumVehicleXPFactor', backwards=False)],
        'relativeOverall':  []
    }
    
_, custom_bonuses = custom_xml_reader.read('gui/extended_params_bonuses.xml')

morePrecisionFormat = {'rounder': backport.getNiceNumberFormat, 'separator': gui.shared.items_parameters.formatters._SLASH, 'precision': 3}
VSTAB_DIRECTIVE_ID = 27643
SNAPSHOT_LEVEL_BONUS = 0.00075      # 0.075% bonus/level
VSTAB_DIRECTIVE_BONUS = 0.05        # 5% bonus
SMOOTH_DRIVING_LEVEL_BONUS = 0.0004 # 0.04% bonus/level

    
# Inserts a new element after the specified element in a tuple
# returns a new tuple since tuples are immutable
def tuple_insert_after(strTuple, newStrElement, afterStrElement=None):
    if not afterStrElement:
        index = -1
    else:
        index = strTuple.index(afterStrElement)
    strList = list(strTuple)
    strList.insert(index+1, newStrElement)
    strTuple = tuple(strList)
    return strTuple

# Inserts a new element after the specified element in a dictionary
# If afterStrElement is not specified, the new element is inserted at the beginning
# WG devs using unordered data structures to store ordered data...
def dict_insert_after(strDict, newStrElement, afterStrElement=None):
    ordered = strDict.items() # Convert dict to iterable list
    if not afterStrElement:
        index = -1
    else:
        index = [pair[0] for pair in ordered].index(afterStrElement)
    ordered.insert(index+1, newStrElement)
    return dict(ordered)

# Add element to a frozenset
# returns a new frozenset since frozensets are immutable
def add_to_frozenset(frozenSet, newStrElement):
    unfrozenSet = set(frozenSet)
    unfrozenSet.add(newStrElement)
    frozenSet = frozenset(unfrozenSet)
    return frozenSet
    
    

##########################################################################################################################################################################################
#
# Parameter calculation functions
#
# Injected into VehicleParams class at runtime
# Injected function names MUST MATCH a paramID specified in CUSTOM_PARAMS, otherwise the game WILL NOT load the param
##########################################################################################################################################################################################

@inject(VehicleParams, 'dispersionPenaltyGunTraverse', is_property=True)
def calcGunTraverseDispersionPenalty(self):

    #return (self._itemDescr.miscAttrs['additiveShotDispersionFactor'],self._itemDescr.miscAttrs['multShotDispersionFactor'])
    #onTurretTraverse = self._itemDescr.gun.shotDispersionFactors['turretRotation'] * self._itemDescr.miscAttrs['additiveShotDispersionFactor'] * self.__factors['chassis/shotDispersionFactors/rotation']
    #onVehTraverse = self._itemDescr.chassis.shotDispersionFactors[1] * self._itemDescr.miscAttrs['additiveShotDispersionFactor'] * self.__factors['gun/shotDispersionFactors/turretRotation']
    
    # Get additive dispersion factors (vstab, irm, etc... bonuses)
    additiveGunStabilizationFactor = self._itemDescr.miscAttrs['additiveShotDispersionFactor']
    crewTrainingFactor = self._VehicleParams__factors['gun/shotDispersionFactors/turretRotation']
    
    # Check if gunner(s) have snap shot skill, get effective skill level
    gunnerSnapShotLevel = 0
    for extra, tankman in self._VehicleParams__vehicle.crew:
        if tankman is None:
            continue
        for skill in tankman.skills:
            if skill.name == 'gunner_smoothTurret' and skill.isActive:
                # Could have 2 gunners with skill active? Only max skill % applies
                gunnerSnapShotLevel = skill.level if (skill.level > gunnerSnapShotLevel) else gunnerSnapShotLevel
    
    # Check if tank has vstab or snap shot directive mounted
    hasStabilizerDirective = False
    for battleBooster in self._VehicleParams__vehicle.battleBoosters.installed:
        if battleBooster and battleBooster.getAffectedSkillName() == 'gunner_smoothTurret':
            gunnerSnapShotLevel = 100 if (gunnerSnapShotLevel < 100) else 200 # Directive doubles effect of skill
        elif battleBooster and battleBooster.intCD == VSTAB_DIRECTIVE_ID:
            hasStabilizerDirective = True
            
    # Compute total dispersion bonus from all equipment, crew skills, and directives
    additiveGunStabilizationFactor -= (SNAPSHOT_LEVEL_BONUS * gunnerSnapShotLevel) # snap shot reduces by 0.075% for each level (up to 15% bonus with snap shot + steady hand directive)
    additiveGunStabilizationFactor -= VSTAB_DIRECTIVE_BONUS if hasStabilizerDirective else 0
    onTurretTraverse = self._itemDescr.gun.shotDispersionFactors['turretRotation'] * additiveGunStabilizationFactor * crewTrainingFactor
    return onTurretTraverse * radians(1.0) # internal value is in degrees?
    
    
@inject(VehicleParams, 'dispersionPenaltyMoving', is_property=True)
def calcMovingDispersionPenalty(self):
    
    additiveGunStabilizationFactor = self._itemDescr.miscAttrs['additiveShotDispersionFactor']

    driverSmoothDrivingLevel = 0
    for extra, tankman in self._VehicleParams__vehicle.crew:
        if tankman is None:
            continue
        for skill in tankman.skills:
            if skill.name == 'driver_smoothDriving' and skill.isActive:
                driverSmoothDrivingLevel = skill.level if (skill.level > driverSmoothDrivingLevel) else driverSmoothDrivingLevel
                
    hasStabilizerDirective = False
    for battleBooster in self._VehicleParams__vehicle.battleBoosters.installed:
        if battleBooster and battleBooster.getAffectedSkillName() == 'driver_smoothDriving':
            driverSmoothDrivingLevel = 100 if (driverSmoothDrivingLevel < 100) else 200 # Directive doubles effect of skill
        elif battleBooster and battleBooster.intCD == VSTAB_DIRECTIVE_ID:
            hasStabilizerDirective = True
            
            
    additiveGunStabilizationFactor -= (SMOOTH_DRIVING_LEVEL_BONUS * driverSmoothDrivingLevel) # snap shot reduces by 0.04% for each level (up to 8% bonus with smooth ride + gearbox intricacy directive)
    additiveGunStabilizationFactor -= VSTAB_DIRECTIVE_BONUS if hasStabilizerDirective else 0
    onMovement = self._itemDescr.chassis.shotDispersionFactors[0] * additiveGunStabilizationFactor * self._VehicleParams__factors['gun/shotDispersionFactors/turretRotation']
    return onMovement / 3.6 # internal value is in m/kph

@inject(VehicleParams, 'engineMaxRpm', is_property=True)
def calcEngineMaxRpm(self):
    return self._itemDescr.engine.rpm_max

@inject(VehicleParams, 'engineMaxTorque', is_property=True)
def calcEngineMaxTorque(self):
    if self._itemDescr.hasTurboshaftEngine:
        peakHp = self.turboshaftEnginePower
    else:
        peakHp = self.enginePower
    return int(peakHp * 5252.0 / self._itemDescr.engine.rpm_max) # Assume peak HP occurs at max rpm (flat torque curve is typically of a diesel engine, also the physics engine likely uses a constant force model)
    
@inject(VehicleParams, 'dispersionPenaltyVehTraverse', is_property=True)
def calcVehTraverseDispersionPenalty(self):

    additiveGunStabilizationFactor = self._itemDescr.miscAttrs['additiveShotDispersionFactor']

    hasStabilizerDirective = False
    for battleBooster in self._VehicleParams__vehicle.battleBoosters.installed:
        if battleBooster and battleBooster.intCD == VSTAB_DIRECTIVE_ID:
            hasStabilizerDirective = True
    additiveGunStabilizationFactor -= VSTAB_DIRECTIVE_BONUS if hasStabilizerDirective else 0
    onVehTraverse = self._itemDescr.chassis.shotDispersionFactors[1] * additiveGunStabilizationFactor * self._VehicleParams__factors['gun/shotDispersionFactors/turretRotation']
    return onVehTraverse * radians(1.0) # internal value is in degrees?
    
@inject(VehicleParams, 'terrainResistance', is_property=True)
def calcTerrainResistances(self):
    factors = self._VehicleParams__getTerrainResistanceFactors()
    rawTerRes = self._itemDescr.chassis.terrainResistance
    return [(x * y) for x, y in zip(factors, rawTerRes)]

@inject(VehicleParams, 'rollingFriction', is_property=True)
def calcRollingFriction(self):
    chassis_physics = self._VehicleParams__getChassisPhysics()
    return (chassis_physics['grounds']['firm']['rollingFriction'], chassis_physics['grounds']['medium']['rollingFriction'], chassis_physics['grounds']['soft']['rollingFriction'])

@inject(VehicleParams, 'cruisingSpeed', is_property=True)
def calcCruisingSpeed(self):
    terrainTopSpeed = self._VehicleParams__getRealSpeedLimit() * self._itemDescr.miscAttrs['enginePowerFactor']
    if self._VehicleParams__hasWheeledSwitchMode() or self._VehicleParams__hasTurboshaftSwitchMode(): # Wheelies and Polish meds have "turbo mode"
        tankTopSpeed = self._VehicleParams__speedLimits(self._itemDescr.siegeVehicleDescr.physics['speedLimits'])
    else:
        tankTopSpeed = self._VehicleParams__speedLimits(self._itemDescr.physics['speedLimits'], ('forwardMaxSpeedKMHTerm', 'backwardMaxSpeedKMHTerm'))
    return min(terrainTopSpeed, tankTopSpeed[0])
    
@inject(VehicleParams, 'premiumVehicleXPFactor', is_property=True)
def calcPremiumVehicleXPFactor(self):
    return self._itemDescr.type.premiumVehicleXPFactor
    #return self._itemDescr.type.xpFactor
    
@inject(VehicleParams, 'relativeExtended', is_property=True)    
def calcRelativeExtended(self):
    return 100
    
@inject(VehicleParams, 'relativeOverall', is_property=True)    
def calcRelativeOverall(self):
    return (self.relativePower + self.relativeArmor + self.relativeMobility + self.relativeCamouflage + self.relativeVisibility) / 5

# end of calculation functions
##########################################################################################################################################################################################


    
##########################################################################################################################################################################################
#
#  Patched (hooked) methods
#  These all require custom functionality, data insertion, or type checking
#  to make all the custom parameters display properly in the garage
##########################################################################################################################################################################################

# Enables strings to be passed as parameter values and displayed
# param comparator assumes operands are numbers
# 'short circuit' original comparator function when either operand is a string
@hook(gui.shared.items_parameters.comparator, '_getParamStateInfo')
def patchedParamComparator(orig, paramName, val1, val2, customReverted = False):

    if isinstance(val1, str) or isinstance(val2, str):
        return (PARAM_STATE.NORMAL, 0)
    
    paramState = orig(paramName, val1, val2, customReverted)
    return paramState
        

@hook(gui.shared.items_parameters.formatters, '_applyFormat')
def enableMorePrecisionFormatting(orig, value, state, settings, doSmartRound, colorScheme):
    if value and not isinstance(value, str) and settings == morePrecisionFormat:
        paramStr = '{0:g}'.format(round(value,settings['precision']))
    else:
        paramStr = value
    return orig(paramStr, state, settings, doSmartRound, colorScheme)


# Force parameter delta to obey same formatting settings as parameter value
# Mainly so small changes in gun dispersion don't get rounded to 0
@hook(gui.shared.items_parameters.formatters, 'formatParameterDelta')
def enableMorePrecisionDelta(orig, pInfo, deltaScheme = None, formatSettings = None):
    return orig(pInfo, deltaScheme, gui.shared.items_parameters.formatters.FORMAT_SETTINGS)
    
    
# Enables the game to calculate/display which equipment/skills affect a certain parameter (when you hover over param in garage)
# Loaded from xml that mirrors original bonus xml, just append the extra ones after loading it
@hook(gui.shared.items_parameters.params_cache._ParamsCache, 'getBonuses')
def addBonusesForCustomParams(orig, self):
    bonuses = orig(self)
    bonuses.update(custom_bonuses)
    return bonuses # call original getBonuses() then return the bonuses with the custom ones inserted
  
  
# Whether or not the parameter category is expanded is stored in account settings
# Instead of trying to mess with the account settings, we can just catch the exceptions
# thrown when the account settings can't find the custom categories
# and then perform the logic ourselves
@hook(VehicleParameters, 'onParamClick')
def bypassAccountSettingsForCustomCategories(onParamClick, self, paramID):
    try:
        onParamClick(self, paramID)
    except (KeyError, SoftException):
        if paramID == 'relativeExtended' or paramID == 'relativeOverall':
            self._expandedGroups[paramID] = not self._expandedGroups.get(paramID, False)
            self._setDPUseAnimAndRebuild(False)


@hook(MENU, 'tank_params', is_class_method=True)
def getCustomParamTextResource(tank_params, cls, key0):
    text = tank_params(key0)
    if text: # text == None means string resource didn't get localized
        return text
    
    return '#custom:tank_params/{}'.format(key0)
  
  
@hook(TOOLTIPS, 'tank_params_desc', is_class_method=True)
def getCustomParamDescTextResource(tank_params_desc, cls, key0):
    text = tank_params_desc(key0)
    if text: # text == None means string resource didn't get localized
        return text
    
    return '#custom:tank_params/desc/{}'.format(key0)


# end of patched methods 
##########################################################################################################################################################################################
    
    
    
##########################################################################################################################################################################################
#
#  Shit that doesn't work but may be useful in the future
#
##########################################################################################################################################################################################

'''@inject(gui.shared.items_parameters.formatters, '_morePrecisionFormat')
def addMorePrecisionSetting():
     return morePrecisionFormat'''
     
# VehicleParameters._expandedGroups needs work to enable custom parameter categories
# Currently the default values are stored in account settings,
# injecting custom strings into that is difficult and could
# potentially cause server desync/ other issues
#@hook(VehicleParameters, '__init__')
def retrieveAccountSettings(orig, self):
    orig(self)
    #self._expandedGroups['relativeExtended'] = True
    #self._expandedGroups['relativeOverall'] = False
    print '[PLAYER] ',type(BigWorld.player())
    return
    
#@hook(VehicleParameters, '_populate')
def addCustomParamCategory(orig, self):
    self._expandedGroups['relativeExtended'] = False
    self._expandedGroups['relativeOverall'] = False

# How dangerous? Also AccountSettings module doesn't import properly, can't directly access module global fields (AttributeError)
#AccountSettings._setValue('relativeExtended', False, sys.modules[AccountSettings.__module__].KEY_SETTINGS, True)
#AccountSettings._setValue('relativeOverall', False, sys.modules[AccountSettings.__module__].KEY_SETTINGS, True)
#sys.modules[AccountSettings.__module__].KEY_SETTINGS['relativeExtended'] = False
#sys.modules[AccountSettings.__module__].KEY_SETTINGS['relativeOverall'] = False
    
            
# Manually add our custom parameter categories to the formatted list returned to display in the garage
#@hook(gui.shared.items_parameters.formatters, 'getAllParametersTitles')
def addCustomParamCategoryFormatting(orig):
    result = orig()
    data = gui.shared.items_parameters.formatters.getCommonParam('simpleTop', 'relativeOverall')
    data['titleText'] = gui.shared.items_parameters.formatters.formatVehicleParamName('relativeOverall')
    data['isEnabled'] = True
    data['tooltip'] = 'baseVehicleParameters'
    result.append(data)
    data = gui.shared.items_parameters.formatters.getCommonParam('advanced', 'relativeOverall')
    data['iconSource'] = gui.shared.items_parameters.formatters.getParameterSmallIconPath('relativeOverall')
    data['titleText'] = gui.shared.items_parameters.formatters.formatVehicleParamName('relativeOverall')
    data['isEnabled'] = False
    data['tooltip'] = 'baseVehicleParameters'
    result.append(data)
    print '[getAllParametersTitles] ', result
    return result

from threading import Thread
from time import sleep
import Vehicular


def threaded_function(arg):
    with open('BigWorld.dump', 'w+') as f:
        print >>f, sys.builtin_module_names
        print >>f, 'Dumping BigWorld module...'
        for name, data in inspect.getmembers(BigWorld):
            print >>f, '{} : {!r}'.format(name, data)
            
            if inspect.isclass(data) or inspect.ismethod(data) or inspect.isfunction(data) or inspect.isbuiltin(data):
                for name2, data2 in inspect.getmembers(data):
                    print >>f, '    {} : {!r}'.format(name2, data2)
                       
                print >>f, '\n'
    with open('Vehicular.dump', 'w+') as f:
        print >>f, 'Dumping Vehicular module...'
        for name, data in inspect.getmembers(Vehicular):
            print >>f, '{} : {!r}'.format(name, data)
            
            if inspect.isclass(data) or inspect.ismethod(data) or inspect.isfunction(data) or inspect.isbuiltin(data):
                for name2, data2 in inspect.getmembers(data):
                    print >>f, '    {} : {!r}'.format(name2, data2)
                        
                    if inspect.ismethod(data2) or inspect.isfunction(data2):
                        print >>f, '        ',inspect.getfullargspec(data2)
                        print >>f, '\n'  
                print >>f, '\n' 


thread = Thread(target = threaded_function, args = (10, ))
#thread.start()



# end of broken shit
##########################################################################################################################################################################################


RELATIVE_EXTENDED_PARAMS = ()


def parse_custom_param_categories():
    for param_category in CUSTOM_PARAM_CATEGORIES:
        gui.shared.items_parameters.RELATIVE_PARAMS = tuple_insert_after(gui.shared.items_parameters.RELATIVE_PARAMS, param_category.paramID, param_category.afterParamID)
        gui.shared.items_parameters.params_helper.RELATIVE_PARAMS = gui.shared.items_parameters.RELATIVE_PARAMS
        gui.shared.items_parameters.formatters.RELATIVE_PARAMS = gui.shared.items_parameters.RELATIVE_PARAMS
        gui.shared.items_parameters.params_helper.EXTRA_PARAMS_GROUP[param_category.paramID] = ()
    print gui.shared.items_parameters.formatters.PARAMS_GROUPS
    print gui.shared.items_parameters.params_helper.EXTRA_PARAMS_GROUP
    print gui.shared.items_parameters.RELATIVE_PARAMS
    gui.shared.items_parameters.formatters.VEHICLE_PARAMS = tuple(chain(*[gui.shared.items_parameters.formatters.PARAMS_GROUPS[param] for param in gui.shared.items_parameters.RELATIVE_PARAMS]))
    

# Parse the list of custom parameters and add them to the game at runtime
def parse_custom_params():
    global RELATIVE_EXTENDED_PARAMS
    for param_category, param_list in CUSTOM_PARAMS.iteritems():
    
        gui.shared.items_parameters.params_helper.PARAMS_GROUPS[param_category] = ()
        gui.shared.items_parameters.formatters.PARAMS_GROUPS[param_category] = ()
        
    
        for param in param_list:
            if param_category == 'relativePower':
                relativeParams = gui.shared.items_parameters.params_helper.RELATIVE_POWER_PARAMS
                relativeParams = tuple_insert_after(relativeParams, param.paramID, param.afterParamID)
                gui.shared.items_parameters.params_helper.RELATIVE_POWER_PARAMS = relativeParams   

            elif param_category == 'relativeArmor':
                relativeParams = gui.shared.items_parameters.params_helper.RELATIVE_ARMOR_PARAMS
                relativeParams = tuple_insert_after(relativeParams, param.paramID, param.afterParamID)
                gui.shared.items_parameters.params_helper.RELATIVE_ARMOR_PARAMS = relativeParams   

            elif param_category == 'relativeMobility':
                relativeParams = gui.shared.items_parameters.params_helper.RELATIVE_MOBILITY_PARAMS
                relativeParams = tuple_insert_after(relativeParams, param.paramID, param.afterParamID)
                gui.shared.items_parameters.params_helper.RELATIVE_MOBILITY_PARAMS = relativeParams   
            
            elif param_category == 'relativeCamouflage':
                relativeParams = gui.shared.items_parameters.params_helper.RELATIVE_CAMOUFLAGE_PARAMS
                relativeParams = tuple_insert_after(relativeParams, param.paramID, param.afterParamID)
                gui.shared.items_parameters.params_helper.RELATIVE_CAMOUFLAGE_PARAMS = relativeParams   
            
            elif param_category == 'relativeVisibility':
                relativeParams = gui.shared.items_parameters.params_helper.RELATIVE_VISIBILITY_PARAMS
                relativeParams = tuple_insert_after(relativeParams, param.paramID, param.afterParamID)
                gui.shared.items_parameters.params_helper.RELATIVE_VISIBILITY_PARAMS = relativeParams

            elif param_category == 'relativeExtended':
                RELATIVE_EXTENDED_PARAMS = tuple_insert_after(RELATIVE_EXTENDED_PARAMS, param.paramID, param.afterParamID)
                relativeParams = RELATIVE_EXTENDED_PARAMS                

            gui.shared.items_parameters.params_helper.PARAMS_GROUPS[param_category] = relativeParams
            gui.shared.items_parameters.formatters.PARAMS_GROUPS[param_category] = relativeParams
            
            if param.backwards:
                gui.shared.items_parameters.comparator._BACKWARD_QUALITY_PARAMS = add_to_frozenset(gui.shared.items_parameters.comparator._BACKWARD_QUALITY_PARAMS, param.paramID)

            gui.shared.items_parameters.formatters.MEASURE_UNITS[param.paramID] = MENU.TANK_PARAMS_M
            gui.shared.items_parameters.formatters.FORMAT_SETTINGS[param.paramID] = morePrecisionFormat
    print gui.shared.items_parameters.formatters.VEHICLE_PARAMS
                

   
parse_custom_params()
parse_custom_param_categories()
print '[EXTENDED VEH. PARAMS.] Version 1.0.0'
print '[EXTENDED VEH. PARAMS.] Mod loaded successfully! v1.0.0'