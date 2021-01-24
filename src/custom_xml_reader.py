import resource_helper

def _getBonusTypesGenerator(bonusTypes):
    for bonusType, items in bonusTypes.items():
        for itemName in items:
            yield (itemName, bonusType)


def read(xml_path):
    params = {}
    for item in resource_helper.root_iterator(xml_path):
        params[item.name] = item.value

    coefficients = params.pop('coefficients')
    bonuses = params.pop('bonuses')
    for paramName, bonusTypes in bonuses.iteritems():
        bonuses[paramName] = tuple(_getBonusTypesGenerator(bonusTypes))

    return (coefficients, bonuses)