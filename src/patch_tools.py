import types

##########################################################################################################################################################################################
#
#  Patching tools - inject methods, variables, etc... (any attribute really) and hook existing methods (intercept its parameters, return your own value)
#  These leverage python's method decorators
##########################################################################################################################################################################################

# Injects an attribute for the decorated method into the specified class
# Method is then 'visible' to anyone who references the class
# If method with matching attribute name already exists: existing method is overwritten with injected method
# Otherwise injected method is added to class
def inject(cls, name, is_property=False, is_class_method=False, is_static_method=False):
    def decorator(func): 
        if is_property:
            setattr(cls, name, property(func))
        elif is_class_method:
            setattr(cls, name, classmethod(func))
        elif is_static_method:
            setattr(cls, name, staticmethod(func))
        else:
            setattr(cls, name, func)
        return func
    return decorator
    
# Example usage of @inject:



# NEVER USE THIS DECORATOR DIRECTLY!!!! Use @hook instead
def add_hook(cls, name, callback):
    orig = getattr(cls, name, None)
    if not orig:
        raise AttributeError('Hook target \'{}\' does not exist in {}!'.format(name,cls)) # getattr() raises AttributeError if attribute doesn't exist, however we should a print a specific explanation 
    if type(orig) != types.MethodType:
        raise AttributeError('Hook target \'{}\' must be a method!'.format(name,cls))
    def victim(func):
        def intercept(*args, **kwargs):
            return callback(func, *args, **kwargs) # Intercept target method and its params
        return intercept
    
    
    

# Intercepts calls to existing function, modify the call's args
# Set is_property if the method you're hooking needs to be rewrapped in a property decorator
# When using hooks, you MUST retain optional/positional arguments 
# hooking method signature must match target's signature, with an additional 1st arg for the target function
def hook(cls, name, is_property=False, is_class_method=False):
    def decorator(callback):
        # Add hook to target
        target = getattr(cls, name, None)
        if not target:
            raise AttributeError('Hook target \'{}\' does not exist in {}!'.format(name,cls)) # getattr() raises AttributeError if attribute doesn't exist, however we should a print a specific explanation 
        def victim(func):
            def intercept(*args, **kwargs):
                return callback(func, *args, **kwargs) # Intercept target method and its args
            return intercept
        
        # Replace target method with a dummy method to intercept the call to the target method
        # Hooking static and class methods needs to be handled properly
        #if isinstance(target, classmethod):
        if is_class_method:
            setattr(cls, name, classmethod(victim(target)))
        elif isinstance(target, staticmethod):
            setattr(cls, name, staticmethod(victim(target)))
        elif isinstance(target, property):
            setattr(cls, name, property(victim(target)))
        else:
            setattr(cls, name, victim(target))
            
    return decorator

# Example usage of @hook: