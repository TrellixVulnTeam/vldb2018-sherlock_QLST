# --------------------------------------------------------------------------
# Source file provided under Apache License, Version 2.0, January 2004,
# http://www.apache.org/licenses/
# (c) Copyright IBM Corp. 2015, 2016
# --------------------------------------------------------------------------
# Author: Olivier OUDOT, IBM Analytics, France Lab, Sophia-Antipolis

"""
This module contains the basic classes representing the expressions required to
describe a constraint programming model.

In particular, it defines the following classes:

 * :class:`CpoExpr`: the root class of each model expression node,
 * :class:`CpoIntVar`: representation of an integer variable,
 * :class:`CpoIntervalVar`: representation of an interval variable,
 * :class:`CpoSequenceVar`: representation of a sequence variable,
 * :class:`CpoTransitionMatrix`: representation of a transition matrix,
 * :class:`CpoStateFunction`: representation of a state function.

**None of these classes should be created explicitly.**
There are various factory functions to do so, such as:

 * :meth:`integer_var`, :meth:`integer_var_list`, :meth:`integer_var_dict` to create integer variable(s),
 * :meth:`binary_var`, :meth:`binary_var_list`, :meth:`binary_var_dict` to create integer variable(s) with value in [0..1],
 * :meth:`interval_var`, :meth:`interval_var_list`, :meth:`interval_var_dict` to create interval variable(s),
 * :meth:`sequence_var` to create a sequence variable,
 * :meth:`transition_matrix` to create a transition matrix,
 * :meth:`tuple_set` to create a tuple set,
 * :meth:`state_function` to create a state function.

Moreover, some automatic conversions are also provided to generate CP Optimizer objects from Python objects.
For example:

 * an integer is converted into CP constant,
 * an iterator of objects is converted in CP array of objects of the corresponding type,
 * a tuple of tuples is converted into tuple set.


Detailed description
--------------------
"""

from docplex.cp.utils import *
from docplex.cp.catalog import *
from docplex.cp.config import context

import threading
import warnings


###############################################################################
## Constants
###############################################################################

INT_MAX = (2**53 - 1)  # (2^53 - 1) for 64 bits, (2^31 - 1) for 32 bits
""" Maximum integer value. """

INT_MIN = -INT_MAX
""" Minimum integer value. """

DEFAULT_INTEGER_VARIABLE_DOMAIN = ((INT_MIN, INT_MAX))
""" Default integer variable domain """

# Name generator for integer variables
_INTEGER_VARIABLE_ID_ALLOCATOR = SafeIdAllocator('_INT_')

# Name generator for interval variables
_INTERVAL_VARIABLE_ID_ALLOCATOR = SafeIdAllocator('_ITV_')

# Name generator for sequence variables
_SEQUENCE_VARIABLE_ID_ALLOCATOR = SafeIdAllocator('_SEQ_')

# Name generator for state functions
_STATE_FUNCTION_ID_ALLOCATOR = SafeIdAllocator('_FUN_')

# Name generator for all other variables
_VARIABLE_ID_ALLOCATOR = SafeIdAllocator('_VAR_')

# Name generator for shared expressions
_EXPRESSION_ID_ALLOCATOR = SafeIdAllocator('_EXP_')

# Name generator for constraints
_CONSTRAINT_ID_ALLOCATOR = SafeIdAllocator('_CTR_')

# Floating point precision to verify equality of floats
_FLOATING_POINT_PRECISION = 1e-9

# Domain for binary variables
_BINARY_DOMAIN = ((0, 1),)


###############################################################################
## Public expression classes
###############################################################################

class CpoExpr(object):
    """ This class is an abstract class that represents any CPO expression node.

    It does not contain links to children expressions that are implemented in extending classes.
    However, method allowing to access to children is provided with default return value.
    """
    __slots__ = ('type',             # Expression result type
                 'name',             # Name of the expression (None if none)
                 'priority',         # Operation priority
                 'children',         # List of children, empty tuple if none
                 'reference_count',  # Number of references on this expression
                )

    # To force possible numpy operators overloading to get CPO expressions as main operand
    __array_priority__ = 100

    # Expression name generator
    __name_generator__ = _EXPRESSION_ID_ALLOCATOR

    def __init__(self, type, name):
        """ Constructor:

        Args:
            type:   Expression type.
            name:   Expression name.
        """
        # super(CpoExpr, self).__init__()
        self.type = type
        self.name = name
        self.reference_count = 0
        self.priority = -1
        self.children = ()

    def __hash__(self):
        """ Redefinition of hash function (mandatory for Python 3)
        """
        return int(id(self) / 16)

    '''
    # These functions are required with standard 'pickle'
    # But DO NOT activate them with cloudpickle
    def __getstate__(self):
        """ Build a picklable object from this object
        """
        return dict((k, getattr(self, k, None)) for k in self.__slots__)

    def __setstate__(self, data):
        """ Fill object from its pickle form
        """
        for (k, v) in data.iteritems():
            setattr(self, k, v)
    '''

    def set_name(self, name):
        """ Set the name of the expression.

        Args:
            name: Expression name, possibly None.
        """
        assert (name is None) or is_string(name), "Argument 'name' should be a string or None, not '{}' of type {}".format(name, type(name))
        if name is not None:
            name = make_unicode(name)
        self.name = name
            
    def get_name(self):
        """ Get the name of the expression.

        Returns:
            Name of the expression, None if not defined
        """
        return self.name

    @classmethod
    def _generate_name(cls):
        """ Generate a name for this type of expression
        Return:
            Unused name for this type of object
        """
        return cls.__name_generator__.allocate()

    def _set_generated_name(self):
        """ Generate a name for this type of expression (with corresponding generator)
        """
        self.name = make_unicode(self._generate_name())

    def is_type(self, xtyp):
        """ Check if the type of this expression is a given one

        Args:
            xtyp:  Expected type
        Returns:
            True if expression type is the expected one
        """
        return self.type == xtyp

    def is_kind_of(self, tp):
        """ Checks if the type of this expression type is compatible with another type.

        Args:
            tp: Other type to check.
        Returns:
           True if this expression type is a kind of tp.
        """
        # Check if required type is the same
        return self.type.is_kind_of(tp)

    def get_max_depth(self):
        """ Gets the maximum expression depth.

        Returns:
            Max expression depth.
        """
        depth = 1
        stack = [[self, -1]]
        while stack:
            selem = stack[-1]
            expr = selem[0]
            if not isinstance(expr, CpoExpr):
                stack.pop()
            else:
                chlds = expr.children
                cnx = selem[1] + 1
                if cnx >= len(chlds):
                    depth = max(depth, len(stack))
                    stack.pop()
                else:
                    selem[1] = cnx
                    stack.append([chlds[cnx], -1])
        return depth

    def equals(self, other):
        """ Checks the equality of this expression with another object.

        Implementation is required with a different name than __eq__ name because this function is already
        overloaded to construct model expression with operator '=='.

        Args:
            other: Other object to compare with.
        Return:
            True if 'other' is equal to this object, False otherwise.
        """
        return _is_equal_expressions(self, other)

    def _equals(self, other):
        """ Checks the equality of this expression with another object.

        This particular method just checks local attributes, but does not check recursively children if any.
        Recursion is implemented by method equals() that uses a self-managed stack to avoid too many
        recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

        Args:
            other: Other object to compare with.
        Return:
            True if 'other' is equal to this object, False otherwise.
        """
        return (type(self) == type(other)) and (self.type == other.type) and (self.name == other.name)

    def _garbage(self):
        """ Signal that the expression is not used.

        This method removes all children and decrement explicit reference_count on children.
        """
        cl = self.children
        self.children = ()
        for c in cl:
            c.reference_count -= 1

    def __str__(self):
        """ Convert this expression into a string """
        if is_string(self.name):
            return to_printable_symbol(self.name) + " = " + _to_string(self)
        else:
            return _to_string(self)

    # Operators overloading

    def __ne__(self, other):
        """ Not equal """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of != should be integer or float expressions"
        return CpoFunctionCall(Oper_diff, Type_BoolExpr, (self, other))

    def __eq__(self, other):
        """ Equal """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of == should be integer or float expressions"
        return CpoFunctionCall(Oper_equal, Type_BoolExpr, (self, other))

    def __gt__(self, other):
        """ Greater """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of > should be integer or float expressions"
        return CpoFunctionCall(Oper_greater, Type_BoolExpr, (self, other))

    def __ge__(self, other):
        """ Greater or equal """
        other = build_cpo_expr(other)
        if self.is_kind_of(Type_IntExpr):
            if other.is_kind_of(Type_FloatExpr):
                return CpoFunctionCall(Oper_greater_or_equal, Type_BoolExpr, (self, other))
            assert other.is_kind_of(Type_CumulExpr), "Operands of >= should be integer, float or cumul expressions"
            return CpoFunctionCall(Oper_greater_or_equal, Type_Constraint, (self, other))
        if self.is_kind_of(Type_FloatExpr):
            assert self.is_kind_of(Type_FloatExpr), "Operands of >= should be integer, float or cumul expressions"
            return CpoFunctionCall(Oper_greater_or_equal, Type_BoolExpr, (self, other))
        assert self.is_kind_of(Type_CumulExpr) and other.is_kind_of(Type_IntExpr), "Operands of >= should be integer, float or cumul expressions"
        return CpoFunctionCall(Oper_greater_or_equal, Type_Constraint, (self, other))

    def __lt__(self, other):
        """ Less """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of < should be integer or float expressions"
        return CpoFunctionCall(Oper_less, Type_BoolExpr, (self, other))

    def __le__(self, other):
        """ Less or equal """
        other = build_cpo_expr(other)
        if self.is_kind_of(Type_IntExpr):
            if other.is_kind_of(Type_FloatExpr):
                return CpoFunctionCall(Oper_less_or_equal, Type_BoolExpr, (self, other))
            assert other.is_kind_of(Type_CumulExpr), "Operands of <= should be integer, float or cumul expressions"
            return CpoFunctionCall(Oper_less_or_equal, Type_Constraint, (self, other))
        if self.is_kind_of(Type_FloatExpr):
            assert self.is_kind_of(Type_FloatExpr), "Operands of <= should be integer, float or cumul expressions"
            return CpoFunctionCall(Oper_less_or_equal, Type_BoolExpr, (self, other))
        assert self.is_kind_of(Type_CumulExpr) and other.is_kind_of(Type_IntExpr), "Operands of <= should be integer, float or cumul expressions"
        return CpoFunctionCall(Oper_less_or_equal, Type_Constraint, (self, other))

    def __add__(self, other):
        """ Plus """
        # if other is 0:  # Do not use == because it is overloaded
        #     return self
        other = build_cpo_expr(other)
        if self.is_kind_of(Type_IntExpr):
            if other.is_kind_of(Type_IntExpr):
                return CpoFunctionCall(Oper_plus, Type_IntExpr, (self, other))
            assert other.is_kind_of(Type_FloatExpr), "Operands of + should be integer, float or cumul"
            return CpoFunctionCall(Oper_plus, Type_FloatExpr, (self, other))
        elif self.is_kind_of(Type_FloatExpr):
            assert other.is_kind_of(Type_FloatExpr), "Operands of + should be integer, float or cumul"
            return CpoFunctionCall(Oper_plus, Type_FloatExpr, (self, other))
        # Sum of cumul expressions
        assert self.is_kind_of(Type_CumulExpr) and other.is_kind_of(Type_CumulExpr), "Operands of + should be integer, float or cumul expressions"
        return CpoFunctionCall(Oper_plus, Type_CumulExpr, (self, other))

    def __radd__(self, other):
        """ Plus (right) """
        # if other is 0:  # Do not use == because it is overloaded
        #     return self
        return build_cpo_expr(other).__add__(self)

    def __pos__(self):
        """ Unary plus """
        return self

    def __sub__(self, other):
        """ Minus """
        other = build_cpo_expr(other)
        if self.is_kind_of(Type_IntExpr):
            if other.is_kind_of(Type_IntExpr):
                return CpoFunctionCall(Oper_minus, Type_IntExpr, (self, other))
            assert other.is_kind_of(Type_FloatExpr), "Operands of - should be integer, float or cumul"
            return CpoFunctionCall(Oper_minus, Type_FloatExpr, (self, other))
        elif self.is_kind_of(Type_FloatExpr):
            assert other.is_kind_of(Type_FloatExpr), "Operands of - should be integer, float or cumul"
            return CpoFunctionCall(Oper_minus, Type_FloatExpr, (self, other))
        # Cumul expressions
        assert self.is_kind_of(Type_CumulExpr) and other.is_kind_of(Type_CumulExpr), "Operands of - should be integer, float or cumul"
        return CpoFunctionCall(Oper_minus, Type_CumulExpr, (self, other))

    def __rsub__(self, other):
        """ Minus (right) """
        return build_cpo_expr(other).__sub__(self)

    def __neg__(self):
        """ Unary minus """
        if self.is_kind_of(Type_IntExpr):
            return CpoFunctionCall(Oper_minus, Type_IntExpr, (self,))
        if self.is_kind_of(Type_FloatExpr):
            return CpoFunctionCall(Oper_minus, Type_FloatExpr, (self,))
        assert self.is_kind_of(Type_CumulExpr), "Operands of - should be integer, float or cumul"
        return CpoFunctionCall(Oper_minus, Type_CumulExpr, (self,))

    def __mul__(self, other):
        """ Multiply """
        other = build_cpo_expr(other)
        if self.is_kind_of(Type_IntExpr):
            if other.is_kind_of(Type_IntExpr):
                return CpoFunctionCall(Oper_times, Type_IntExpr, (self, other))
            assert other.is_kind_of(Type_FloatExpr), "Operands of * should be integer or float"
            return CpoFunctionCall(Oper_times, Type_FloatExpr, (self, other))
        assert other.is_kind_of(Type_FloatExpr), "Operands of * should be integer or float"
        return CpoFunctionCall(Oper_times, Type_FloatExpr, (self, other))

    def __rmul__(self, other):
        """ Multiply (right) """
        return build_cpo_expr(other).__mul__(self)

    def __div__(self, other):
        """ Float divide """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of / should be float or integer expressions"
        return CpoFunctionCall(Oper_float_div, Type_FloatExpr, (self, other))

    def __rdiv__(self, other):
        """ Float divide (right) """
        return build_cpo_expr(other).__div__(self)

    def __truediv__(self, other):
        """ Float divide (Python 3) """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of / should be float or integer expressions"
        return CpoFunctionCall(Oper_float_div, Type_FloatExpr, (self, other))

    def __rtruediv__(self, other):
        """ Float divide (right) (Python 3) """
        return build_cpo_expr(other).__truediv__(self)

    def __floordiv__(self, other):
        """ Integer divide (Python 3) """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_IntExpr) and other.is_kind_of(Type_IntExpr), "Operands of // should be integer expressions"
        return CpoFunctionCall(Oper_int_div, Type_IntExpr, (self, other))

    def __rfloordiv__(self, other):
        """ Integer divide (right) (Python 3) """
        return build_cpo_expr(other).__floordiv__(self)

    def __mod__(self, other):
        """ Modulo """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_IntExpr) and other.is_kind_of(Type_IntExpr), "Operands of % should be integer expressions"
        return CpoFunctionCall(Oper_mod, Type_IntExpr, (self, other))

    def __rmod__(self, other):
        """ Power (right) """
        return build_cpo_expr(other).__mod__(self)

    def __pow__(self, other):
        """ Power """
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_FloatExpr) and other.is_kind_of(Type_FloatExpr), "Operands of ** (power) should be float expressions"
        return CpoFunctionCall(Oper_power, Type_FloatExpr, (self, other))

    def __rpow__(self, other):
        """ Power (right) """
        return build_cpo_expr(other).__pow__(self)

    def __and__(self, other):
        """ Binary and used to represent logical and """
        # if other is True:  # Do not use == because it is overloaded
        #     return self
        # if other is False:  # Do not use == because it is overloaded
        #     return False
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_BoolExpr) and other.is_kind_of(Type_BoolExpr), "Operands of & (logical and) should be boolean expressions"
        return CpoFunctionCall(Oper_logical_and, Type_BoolExpr, (self, other))

    def __rand__(self, other):
        """ Binary and used to represent logical and (right) """
        return build_cpo_expr(other).__and__(self)

    def __or__(self, other):
        """ Binary or used to represent logical or """
        # if other is False:  # Do not use == because it is overloaded
        #     return self
        # if other is True:  # Do not use == because it is overloaded
        #     return True
        other = build_cpo_expr(other)
        assert self.is_kind_of(Type_BoolExpr) and other.is_kind_of(Type_BoolExpr), "Operands of | (logical or) should be boolean expressions"
        return CpoFunctionCall(Oper_logical_or, Type_BoolExpr, (self, other))

    def __ror__(self, other):
        """ Binary or used to represent logical or (right) """
        return build_cpo_expr(other).__or__(self)

    def __invert__(self):
        """ Binary not used to represent logical not (right) """
        assert self.is_kind_of(Type_BoolExpr), "Operands of ~ (logical not) should be a boolean expression"
        return CpoFunctionCall(Oper_logical_not, Type_BoolExpr, (self,))



class CpoValue(CpoExpr):
    """ CPO model expression node representing a constant value. """
    __slots__ = ('value',  # Python value of the constant
                )

    def __init__(self, value, type):
        """ Constructor

        Args:
            value:  Constant value.
            type :  Value type.
        """
        assert isinstance(type, CpoType), "Argument 'type' should be a CpoType"
        super(CpoValue, self).__init__(type, None)
        if type.is_array_of_expr:
            for e in value:
                e.reference_count += 1
            self.children = value
        self.value = value

    def _equals(self, other):
        """ Checks the equality of this expression with another object.

        This particular method just checks local attributes, but does not check recursively children if any.
        Recursion is implemented by method equals() that uses a self-managed stack to avoid too many
        recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

        Args:
            other: Other object to compare with.
        Returns:
            True if 'other' is semantically identical to this object, False otherwise.
        """
        # Call super
        if not super(CpoValue, self)._equals(other):
            return False
        # For array of expr, managed as a recursive call by _equals_expressions().
        if self.type.is_array_of_expr:
            return True
        # Check value
        return _is_equal_values(self.value, other.value)


class CpoFunctionCall(CpoExpr):
    """ This class represent all model expression nodes that call a predefined modeler function.

    All modeling functions are available in module :mod:`docplex.cp.modeler`.
    """
    __slots__ = ('operation',  # Operation descriptor
                )

    def __init__(self, oper, rtype, oprnds):
        """ Constructor
        Args:
            oper:   Operation descriptor
            rtype:  Returned type
            oprnds: List of operand expressions.
        """
        assert isinstance(oper, CpoOperation), "Argument 'oper' should be a CpoOperation"
        super(CpoFunctionCall, self).__init__(rtype, None)
        self.operation = oper
        self.priority = oper.priority

        # Check no toplevel constraints
        for e in oprnds:
            assert not e.is_type(Type_Constraint), "A constraint can not be operand of an expression."
            e.reference_count += 1
        self.children = oprnds

    def _equals(self, other):
        """ Checks the equality of this expression with another object.

        This particular method just checks local attributes, but does not check recursively children if any.
        Recursion is implemented by method equals() that uses a self-managed stack to avoid too many
        recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

        Args:
            other: Other object to compare with.
        Returns:
            True if 'other' is semantically identical to this object, False otherwise.
        """
        return super(CpoFunctionCall, self)._equals(other) and (self.operation == other.operation)


class CpoVariable(CpoExpr):
    """ This class is an abstract class extended by all expression nodes that represent a CPO variable.
    """
    __slots__ = ()

    # Expression name generator
    __name_generator__ = _VARIABLE_ID_ALLOCATOR

    def __init__(self, type, name):
        """ Constructor:

        Args:
            type:   Expression type.
            name:   Variable name.
        """
        # Check name length
        if name is None:
            name = self._generate_name()
        super(CpoVariable, self).__init__(type, name)


class CpoIntVar(CpoVariable):
    """ This class represents an *integer variable* that can be used in a CPO model.

    This object should not be created explicitly, but using one of the following factory method:

    * :meth:`integer_var`, :meth:`integer_var_list`, :meth:`integer_var_dict` to create integer variable(s),
    * :meth:`binary_var`, :meth:`binary_var_list`, :meth:`binary_var_dict` to create integer variable(s)
      with value in [0..1],

    """
    __slots__ = ('domain',  # Variable domain
                 )
    
    # Expression name generator
    __name_generator__ = _INTEGER_VARIABLE_ID_ALLOCATOR

    def __init__(self, dom, name):
        # Private constructor
        super(CpoIntVar, self).__init__(Type_IntVar, name)
        self.domain = dom
        
    def set_domain(self, domain):
        """ Sets the domain of the variable.

        The domain of the variable is a list or tuple of:

           * discrete integer values,
           * list or tuple of 2 integers representing an interval.

        For example, here are valid domain definitions:

           set_domain([1, 3, 4, 5, 9])
           set_domain([1, (3, 5), 9])

        Args:
            domain: List of integers or interval tuples representing the variable domain.
        """
        self.domain = _build_int_var_domain(None, None, domain)

    def get_domain(self):
        """ Gets the domain of the variable.

        Returns:
            List of integers or interval tuples representing the variable domain.
        """
        return self.domain

    def domain_iterator(self):
        """ Iterator on the individual values of an integer variable domain.

        Returns:
            Value iterator on the domain of this variable.
        """
        return _domain_iterator(self.domain)

    def equals(self, other):
        """ Checks if this expression is equivalent to another

        Args:
            other: Other object to compare with.
        Return:
            True if 'other' is semantically identical to this object, False otherwise.
        """
        return super(CpoIntVar, self).equals(other) and (self.domain == other.domain)


###############################################################################
## Scheduling expressions
###############################################################################

INTERVAL_MAX = (INT_MAX // 2) - 1
""" Maximum interval variable range value """

INTERVAL_MIN = -INTERVAL_MAX
""" Minimum interval variable range value """

INFINITY = float('inf')
""" Infinity """

DEFAULT_INTERVAL = (0, INTERVAL_MAX)
""" Default interval. """

# Different interval variable presence states
_PRES_PRESENT   = "present"   # Always present
_PRES_ABSENT    = "absent"    # Always absent
_PRES_OPTIONAL  = "optional"  # Present or absent, choice made by the solver


class CpoIntervalVar(CpoVariable):
    """ This class represents an *interval variable* that can be used in a CPO model.

    This object should not be created explicitly, but using one of the following factory method
    :meth:`interval_var`, :meth:`interval_var_list`, or :meth:`interval_var_dict`.
    """
    __slots__ = ('start',        # Start domain
                 'end',          # End domain
                 'length',       # Length domain
                 'size',         # Size domain
                 'intensity',    # Specifies relation between size and length of the interval.
                 'granularity',  # Scale of the intensity function (int)
                 'presence',     # Presence requirement (in _PRES_*)
                 )

    # Expression name generator
    __name_generator__ = _INTERVAL_VARIABLE_ID_ALLOCATOR

    def __init__(self, start, end, length, size, intensity, granularity, presence, name):
        # Private constructor
        super(CpoIntervalVar, self).__init__(Type_IntervalVar, name)
        self.start   = start
        self.end     = end
        self.length  = length
        self.size    = size
        self.presence = presence
        self.granularity = granularity
        self.intensity = intensity
        if intensity is not None:
            intensity.reference_count += 1
            self.children = (intensity,)

    def set_start(self, intv):
        """ Sets the start interval.

        Args:
            intv: Start of the interval (single integer or interval expressed as a tuple of 2 integers).
        """
        self.start = _check_arg_interval(intv, "intv")

    def get_start(self):
        """ Gets the start of the interval.

        Returns:
            Start of the interval (interval expressed as a tuple of 2 integers).
        """
        return self.start

    def set_start_min(self, mn):
        """ Sets the minimum value of the start interval.

        Args:
            mn: Min value of the start of the interval.
        """
        self.start = (mn, self.start[1])

    def set_start_max(self, mx):
        """ Sets the maximum value of the start interval.

        Args:
            mx: Max value of the start of the interval.
        """
        self.start = (self.start[0], mx)

    def set_end(self, intv):
        """ Sets the end of the interval.

        Args:
            intv: End of the interval (single integer or interval expressed as a tuple of 2 integers).
        """
        self.end = _check_arg_interval(intv, "intv")

    def get_end(self):
        """ Gets the end of the interval.

        Returns:
            End of the interval (interval expressed as a tuple of 2 integers)
        """
        return self.end

    def set_end_min(self, mn):
        """ Sets the minimum value of the end interval.

        Args:
            mn: Min value of the end of the interval.
        """
        self.end = (mn, self.end[1])

    def set_end_max(self, mx):
        """ Sets the maximum value of the end of the interval.

        Args:
            mx: Max value of the end of the interval.
        """
        self.end =(self.end[0], mx)

    def set_length(self, intv):
        """ Sets the length interval.

        Args:
            intv: Length of the interval (single integer or interval expressed as a tuple of 2 integers).
        """
        self.length = _check_arg_interval(intv, "intv")

    def get_length(self):
        """ Gets the length interval.

        Returns:
            Length of the interval (interval expressed as a tuple of 2 integers).
        """
        return self.length

    def set_length_min(self, mn):
        """ Sets the minimum value of the length interval.

        Args:
            mn: Min value of the length of the interval min value.
        """
        self.length = (mn, self.length[1])

    def set_length_max(self, mx):
        """ Sets the maximum value of the length interval.

        Args:
            mx: Max value of the length of the interval.
        """
        self.length = (self.length[0], mx)

    def set_size(self, intv):
        """ Sets the size of the interval.

        Args:
            intv: Size of the interval (single integer or interval expressed as a tuple of 2 integers).
        """
        self.size = _check_arg_interval(intv, "intv")

    def get_size(self):
        """ Gets the size of the interval.

        Returns:
            Size of the interval (interval expressed as a tuple of 2 integers).
        """
        return self.size

    def set_size_min(self, mn):
        """ Sets the minimum value of the size interval.

        Args:
            mn: Min value of the size of the interval.
        """
        self.size = (mn, self.size[1])

    def set_size_max(self, mx):
        """ Sets the maximum value of the size interval.

        Args:
            mx: Max value of the size of the interval.
        """
        self.size = (self.size[0], mx)

    def set_present(self):
        """ Specifies that this IntervalVar must be present. """
        self.presence = _PRES_PRESENT

    def is_present(self):
        """ Check if this interval variable must be present.

        Returns:
            True if this interval variable must be present, False otherwise.
        """
        return self.presence == _PRES_PRESENT

    def set_absent(self):
        """ Specifies that this interval variable must be absent. """
        self.presence = _PRES_ABSENT

    def is_absent(self):
        """ Check if this interval variable must be absent.

        Returns:
            True if this interval variable must be absent, False otherwise.
        """
        return self.presence == _PRES_ABSENT

    def set_optional(self):
        """ Specifies that this interval variable is optional. """
        self.presence = _PRES_OPTIONAL

    def is_optional(self):
        """ Check if this interval variable is optional.

        Returns:
            True if this interval variable is optional, False otherwise.
        """
        return self.presence == _PRES_OPTIONAL

    def set_intensity(self, intensity):
        """ Sets the intensity function of this interval var.

        Args:
           intensity:  Intensity function (None, or StepFunction).
        """
        _check_arg_intensity(intensity, self.granularity)
        self.intensity = intensity
        if intensity is None:
            self.children = ()
        else:
            intensity.reference_count += 1
            self.children = (intensity,)

    def get_intensity(self):
        """ Gets the intensity function of this interval var.

        Returns:
           Intensity function (None, or StepFunction).
        """
        return self.intensity

    def set_granularity(self, granularity):
        """ Sets the scale of the intensity function.

        Args:
            granularity: Scale of the intensity function (integer).
        """
        assert (granularity is None) or (is_int(granularity) and (granularity >= 0)), "Argument 'granularity' should be None or positive integer"
        self.granularity = granularity 

    def get_granularity(self):
        """ Get the scale of the intensity function.

        Returns:
            Scale of the intensity function, None for default (100)
        """
        return self.granularity

    def _equals(self, other):
        """ Checks the equality of this expression with another object.

        This particular method just checks local attributes, but does not check recursively children if any.
        Recursion is implemented by method equals() that uses a self-managed stack to avoid too many
        recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

        Args:
            other: Other object to compare with.
        Returns:
            True if 'other' is semantically identical to this object, False otherwise.
        """
        # Call super
        if not super(CpoIntervalVar, self)._equals(other):
            return False

        # Check same attributes (intensity processed as a children)
        return self.start == other.start and \
               self.end == other.end and \
               self.length == other.length and \
               self.size == other.size and \
               self.granularity == other.granularity and \
               self.presence == other.presence

class CpoSequenceVar(CpoVariable):
    """ This class represents an *sequence variable* that can be used in a CPO model.

    Variables are stored in 'children' attribute
    """
    __slots__ = ('types',  # Variable types
                )
    
    # Expression name generator
    __name_generator__ = _SEQUENCE_VARIABLE_ID_ALLOCATOR

    def __init__(self, vars, types=None, name=None):
        """ Creates a new sequence variable.

        This method creates an instance of sequence variable on the set of interval variables defined
        by the array 'vars'.
        A list of non-negative integer types can be optionally specified.
        List of variables and types must be of the same size and interval variable vars[i] will have type types[i]
        in the sequence variable.

        Args:
            vars:  List of IntervalVars that constitute the sequence.
            types: List of variable types as integers, same size as vars, or None (default).
            name:  Name of the sequence, None for automatic naming.
        """
        # Check  arguments
        if isinstance(vars, CpoValue):
            assert vars.is_kind_of(Type_IntervalVarArray)
            vars = vars.value
        else:
            assert is_array_of_type(vars, CpoIntervalVar), "Argument 'vars' should be an array of CpoIntervalVar"
        if types is not None:
            if isinstance(types, CpoValue):
                assert types.is_kind_of(Type_IntArray)
                types = types.value
            else:
                types = _check_and_expand_interval_tuples('types', types)
            assert len(types) == len(vars), "The array of types should have the same length than the array of variables."
        # Store attributes
        super(CpoSequenceVar, self).__init__(Type_SequenceVar, name)
        self.children = tuple(vars)
        self.types = types

    def get_interval_variables(self):
        """ Gets the array of variables.

        Returns:
            Array of interval variables that are in the sequence.
        """
        return self.children
    
    def get_vars(self):
        """ Gets the array of variables in this sequence variable.

        Returns:
            Array of interval variables
        """
        return self.children
    
    def get_types(self):
        """ Gets the array of types.

        Returns:
            Array of variable types (array of integers), None if no type defined.
        """
        return self.types

    def _equals(self, other):
        """ Checks the equality of this expression with another object.

        This particular method just checks local attributes, but does not check recursively children if any.
        Recursion is implemented by method equals() that uses a self-managed stack to avoid too many
        recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

        Args:
            other: Other object to compare with.
        Returns:
            True if 'other' is semantically identical to this object, False otherwise.
        """
        # Call super
        if not super(CpoSequenceVar, self)._equals(other):
            return False
        # Check equality of types
        if self.types != other.types:
            return False
        # List of variables is processed as expression children
        return True

    def __len__(self):
        """ Get the length of the sequence variable (number of variables) """
        return len(self.children)


class CpoTransitionMatrix(CpoValue):
    """ This class represents a *transition matrix* that is used in CPO model to represent transition distances.
    """
    __slots__ = ()  # Matrix stored in value field

    def __init__(self, size=None, values=None, name=None):
        """ Creates a new transition matrix (square matrix of integers).

        A transition matrix is a square matrix of non-negative integers that represents a minimal distance between
        two interval variables.
        An instance of transition matrix can be used in the no_overlap constraint and in state functions.

          * In a no_overlap constraint the transition matrix represents the minimal distance between two
            non-overlapping interval variables.
            The matrix is indexed using the integer types of interval variables in the sequence variable
            of the no_overlap constraint.

          * In a state function, the transition matrix represents the minimal distance between two integer
            states of the function.

        A transition matrix can be created:

          * Deprecated.
            Giving only its size. In this case, a transition matrix is created by this constructor with all
            values initialized to zero. Matrix values can then be set using :meth:`set_value` method.

          * Giving the matrix values as a list of rows, each row being a list of integers.
            Matrix values can not be changed after it has been created.

        Args:
            size (optional):   Matrix size (width and height),
            name (optional):   Name of the matrix. None by default.
            values (optional): Matrix values expressed as a list of rows.
        """

        super(CpoTransitionMatrix, self).__init__(None, Type_TransitionMatrix)
        if name:
            self.set_name(name)

        # Check type of argument
        if size:
            assert is_int(size) and size >= 0, "Argument 'size' should be a positive integer."
            assert values is None, "Arguments 'size' and 'values' should not be given together."
            warnings.warn("Creating editable transition matrix by size is deprecated since release 2.3.",
                          DeprecationWarning)
            self.value = [[0 for i in range(size)] for j in range(size)]
        else:
            try:
                self.value = tuple(tuple(x) for x in values)
            except TypeError:
                assert False, "Argument 'values' should be an iterable of iterables of integers."
            size = len(self.value)
            assert all (len(x) == size for x in self.value), \
                "Matrix value should be squared (list of rows of the same size)"
            assert all(all(is_int(v) and v >= 0 for v in r) for r in self.value), \
                "All matrix values should be positive integers"

    def get_size(self):
        """ Returns the size of the matrix.

        Returns:
            Matrix size.
        """
        return len(self.value)

    def get_value(self, from_state, to_state):
        """ Returns a value in the transition matrix.

        Args:
            from_state: Index of the from state.
            to_state:   Index of the to state.
        Returns:
            Transition value.
        """
        return self.value[from_state][to_state]

    def get_all_values(self):
        """ Returns an iterator on all matrix values, in row/column order

        Returns:
            Iterator on all values
        """
        sizerg = range(len(self.value))
        return (self.value[f][t] for f in sizerg for t in sizerg)

    def get_matrix(self):
        """ Returns the complete transition matrix.

        Returns:
            Transition matrix as a list of integers that is the concatenation of all matrix rows.
        """
        return self.value

    def set_value(self, from_state, to_state, value):
        """ Sets a value in the transition matrix.

        Args:
            from_state: Index of the from state.
            to_state:   Index of the to state.
            value:      Transition value.
        """
        assert is_int(value) and value >= 0, "Value should be a positive integer"
        self.value[from_state][to_state] = value


class CpoStateFunction(CpoVariable):
    """ This class represents a *state function* expression node.

    State functions are used by *interval variables* to represent the evolution of a state variable over time.
    """
    __slots__ = ('trmtx',  # Transition matrix
                )

    # Expression name generator
    __name_generator__ = _STATE_FUNCTION_ID_ALLOCATOR

    def __init__(self, trmtx=None, name=None):
        """ Creates a new state function.

        Args:
            trmtx (optional): An optional transition matrix defining the transition distance between consecutive states
                              of the state function.
                              Transition matrix is given as a list of rows (iterable of iterables of positive integers),
                              or as the result of a call to the method :meth:`~docplex.cp.expression.transition_matrix`.
            name (optional):   Name of the state function.
        """
        # Force name for state functions
        super(CpoStateFunction, self).__init__(Type_StateFunction, name)
        self.set_transition_matrix(trmtx)

    def set_transition_matrix(self, trmtx):
        """ Sets the transition matrix.

        Args:
        trmtx : A transition matrix defining the transition distance between consecutive states of the state function.
                Transition matrix is given as a list of rows (iterable of iterables of positive integers),
                or as the result of a call to the method :meth:`~docplex.cp.expression.transition_matrix`.
        """

        if trmtx is None:
            self.trmtx = None
            self.children = ()
        else:
            trmtx =  build_cpo_transition_matrix(trmtx)
            self.trmtx = trmtx
            assert isinstance(trmtx, CpoTransitionMatrix), "Argument 'trmtx' should be a CpoTransitionMatrix"
            trmtx.reference_count += 1
            self.children = (trmtx,)

    def get_transition_matrix(self):
        """ Returns the transition matrix.

        Returns:
            Transition matrix, None if none.
        """
        return self.trmtx

    def _equals(self, other):
        """ Checks the equality of this expression with another object.

        This particular method just checks local attributes, but does not check recursively children if any.
        Recursion is implemented by method equals() that uses a self-managed stack to avoid too many
        recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

        Args:
            other: Other object to compare with.
        Returns:
            True if 'other' is semantically identical to this object, False otherwise.
        """
        return super(CpoStateFunction, self)._equals(other)
        # Transition matrix is checked as children



###############################################################################
## Factory Functions
###############################################################################

def integer_var(min=None, max=None, name=None, domain=None):
    """ Creates an integer variable.

    An integer variable is a decision variable with a set of potential values called 'domain of the variable'.
    This domain can be expressed either:

     * as a single interval, with a minimum and a maximum bounds included in the domain,
     * or as an extensive list of values and/or intervals.

    When the domain is given extensively, an interval of the domain is represented by a tuple (min, max).
    Examples of variable domains expressed extensively are:

     * (1, 2, 3, 4)
     * (1, 2, (3, 7), 9)
     * ((1, 2), (7, 9))

    Following integer variable declarations are equivalent:

     * v = integer_var(0, 9, "X")
     * v = integer_var(domain=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), name="X")
     * v = integer_var(domain=(0, (1, 5), (6, 7), 8, 9), name="X")
     * v = integer_var(domain=((0, 9)), name="X")

    Args:
        min:    Domain min value. Optional if domain is given extensively.
        max:    Domain max value. Optional if domain is given extensively.
        name:   Optional variable name. If not given, a name is automatically generated.
        domain: Variable domain expressed as extensive list of values and/or intervals expressed as tuples of integers.
                Unused if min and max are provided.
    Returns:
        CpoIntVar expression
    """
    return CpoIntVar(_build_int_var_domain(min, max, domain), name)


def integer_var_list(size, min=None, max=None, name=None, domain=None):
    """ Creates a list of integer variables.

    This methods creates a list of integer variables whose size is given as first parameter.
    All other parameters are identical to those requested by the method integer_var()
    that allows to create a single integer variable.
    See the documentation of :meth:`integer_var` for details.

    If a name is given, each variable of the list is created with this
    name concatenated with the index of the variable in the list, starting by zero.

    Args:
        size:   Size of the list of variables
        min:    Domain min value. Optional if domain is given extensively.
        max:    Domain max value. Optional if domain is given extensively.
        name:   Optional variable name prefix. If not given, a name is automatically generated.
        domain: Variable domain expressed as extensive list of values and/or intervals expressed as tuples of integers.
                Unused if min and max are provided.
    Returns:
        List of integer variables.
    """
    if name is None:
        name = CpoIntVar._generate_name() + "_"
    dom = _build_int_var_domain(min, max, domain)
    res = []
    for i in range(size):
        res.append(CpoIntVar(dom, name + str(i)))
    return res


def integer_var_dict(keys, min=None, max=None, name=None, domain=None):
    """ Creates a dictionary of integer variables.

    This methods creates a dictionary of integer variables associated to a list of keys given as first parameter.
    All other parameters are identical to those requested by the method integer_var()
    that allows to create a single integer variable.
    See the documentation of :meth:`integer_var` for details.

    If a name is given, each variable of the list is created with this
    name concatenated with the string representation of the corresponding key.
    The parameter 'name' can also be a function that is called to build the variable name
    with the variable key as parameter.

    Args:
        keys:   Iterable of variable keys.
        min:    Domain min value. Optional if domain is given extensively.
        max:    Domain max value. Optional if domain is given extensively.
        name:   Optional variable name. If not given, a name is automatically generated.
        domain: Variable domain expressed as extensive list of values and/or intervals expressed as tuples of integers.
                Unused if min and max are provided.
    Returns:
        Dictionary of CpoIntVar objects.
    """
    if name is None:
        name = CpoIntVar._generate_name() + "_"
    dom = _build_int_var_domain(min, max, domain)

    res = {}
    i = 0
    isnamestr = is_string(name)
    for k in keys:
        if isnamestr:
            vname = name + str(i)
        else:
            vname = name(k)
        res[k] = CpoIntVar(dom, vname)
        i += 1
    return res


def binary_var(name=None):
    """ Creates a binary integer variable.

    An binary variable is an integer variable with domain limited to 0 and 1

    Args:
        name (optional): Variable name, default is None for automatic name.
    Returns:
        CpoIntVar expression
    """
    return CpoIntVar(_BINARY_DOMAIN, name)


def binary_var_list(size, name=None):
    """ Creates a list of binary variables.

    This methods creates a list of binary variables.

    If a name is given, each variable of the list is created with this
    name concatenated with the index of the variable in the list, starting by zero.

    Args:
        size: Size of the list of variables
        name (optional): Variable name prefix. If not given, a name prefix is generated automatically.
    Returns:
        List of binary integer variables.
    """
    return integer_var_list(size, _BINARY_DOMAIN, name=name)


def binary_var_dict(keys, name=None):
    """ Creates a dictionary of binary variables.

    This methods creates a dictionary of binary variables associated to a list of keys given as first parameter.

    If a name is given, each variable of the list is created with this
    name concatenated with the string representation of the corresponding key.
    The parameter 'name' can also be a function that is called to build the variable name
    with the variable key as parameter.

    Args:
        keys: Iterable of variable keys.
        name (optional): Variable name prefix, or function to be called on dictionary key (example: str).
                         If not given, a name prefix is generated automatically.
    Returns:
        Dictionary of CpoIntVar objects (OrderedDict).
    """
    return integer_var_dict(keys, _BINARY_DOMAIN, name=name)


def interval_var(start=None, end=None, length=None, size=None,
                 intensity=None, granularity=None, optional=False, name=None):
    """ Creates an interval variable.

    An interval decision variable represents an unknown of a scheduling problem, in particular an interval of time
    during which something happens (an activity is carried out) whose position in time is unknown.
    An interval is characterized by a start value, an end value and a size.
    The start and end of an interval variable must be in [INTERVAL_MIN..INTERVAL_MAX].
    An important feature of interval decision variables is that they can be optional, that is, it is possible
    to model that an interval variable can be absent from the solution schedule.

    Sometimes the intensity of work is not the same during the whole interval.
    For example, consider a worker who does not work during weekends (his work intensity during weekends is 0%)
    and on Friday he works only for half a day (his intensity during Friday is 50%).
    For this worker, 7 man-days work will span for longer than just 7 days.
    In this example 7 man-days represent what is called the size of the interval: that is, the length of the
    interval would be if the intensity function was always at 100%.
    To model such situations, a range for the size of an interval variable and an integer stepwise intensity
    function can be specified.
    The length of the interval will be at least long enough to cover the work requirements
    given by the interval size, taking into account the intensity function.

    Args:
        start (optional):       Allowed range for the start of the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        end (optional):         Allowed range for the end the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        length (optional):      Allowed range for the length the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        size (optional):        Allowed range for the size the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        intensity (optional):   StepFunction that specifies relation between size and length of the interval.
        granularity (optional): Scale of the intensity function.
        optional (optional):    Optional presence indicator.
        name (optional):        Name of the variable. If not given, a name is generated automatically.
    Returns:
        IntervalVar expression.
    """
    start  = _check_arg_interval(start,  "start")
    end    = _check_arg_interval(end,    "end")
    length = _check_arg_interval(length, "length")
    size   = _check_arg_interval(size,   "size")
    _check_arg_intensity(intensity, granularity)
    #presence = _PRES_OPTIONAL if (_check_arg_boolean(optional, "optional") or not present) else _PRES_PRESENT
    presence = _PRES_OPTIONAL if (_check_arg_boolean(optional, "optional")) else _PRES_PRESENT
    return CpoIntervalVar(start, end, length, size, intensity, granularity, presence, name)


def interval_var_list(asize, start=None, end=None, length=None, size=None,
                 intensity=None, granularity=None, optional=False, name=None):
    """ Creates a list of interval variables.

    If a name is given, each variable of the array is created with this
    name concatenated with the index of the variable in the list.

    Args:
        asize:                  Size of the list of variables
        start (optional):       Allowed range for the start of the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        end (optional):         Allowed range for the end the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        length (optional):      Allowed range for the length the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        size (optional):        Allowed range for the size the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        intensity (optional):   StepFunction that specifies relation between size and length of the interval.
        granularity (optional): Scale of the intensity function.
        optional (optional):    Optional presence indicator.
        name (optional):        Name of the variable. If not given, a name is generated automatically.
    Returns:
        List of interval variables.
    """
    start  = _check_arg_interval(start,  "start")
    end    = _check_arg_interval(end,    "end")
    length = _check_arg_interval(length, "length")
    size   = _check_arg_interval(size,   "size")
    _check_arg_intensity(intensity, granularity)
    presence = _PRES_OPTIONAL if (_check_arg_boolean(optional, "optional")) else _PRES_PRESENT

    if name is None:
        name = CpoIntervalVar._generate_name() + "_"
    res = []
    for i in range(asize):
        res.append(CpoIntervalVar(start, end, length, size, intensity, granularity, presence, name + str(i)))
    return res


def interval_var_dict(keys, start=None, end=None, length=None, size=None,
                 intensity=None, granularity=None, optional=False, name=None):
    """ Creates a list of interval variables.

    If a name is given, each variable of the array is created with this
    name concatenated with the index of the variable in the list.

    Args:
        keys:                   Iterable of variable keys.
        start (optional):       Allowed range for the start of the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        end (optional):         Allowed range for the end the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        length (optional):      Allowed range for the length the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        size (optional):        Allowed range for the size the interval (single integer or interval expressed as a tuple of 2 integers).
                                Default value is [0..INTERVAL_MAX].
        intensity (optional):   StepFunction that specifies relation between size and length of the interval.
        granularity (optional): Scale of the intensity function.
        optional (optional):    Optional presence indicator.
        name (optional):        Variable name prefix, or function to be called on dictionary key (example: str).
                                If not given, a name prefix is generated automatically.
    Returns:
        Dictionary of CpoIntervalVar objects.
    """
    start  = _check_arg_interval(start,  "start")
    end    = _check_arg_interval(end,    "end")
    length = _check_arg_interval(length, "length")
    size   = _check_arg_interval(size,   "size")
    _check_arg_intensity(intensity, granularity)
    presence = _PRES_OPTIONAL if (_check_arg_boolean(optional, "optional")) else _PRES_PRESENT

    if name is None:
        name = CpoIntervalVar._generate_name() + "_"

    res = {}
    i = 0
    isnamestr = is_string(name)
    for k in keys:
        if isnamestr:
            vname = name + str(i)
        else:
            vname = name(k)
        res[k] = CpoIntervalVar(start, end, length, size, intensity, granularity, presence, vname)
        i += 1
    return res


def sequence_var(vars, types=None, name=None):
    """ Creates a new sequence variable (list of interval variables).

    This method creates an instance of sequence variable on the set of interval variables defined
    by the array 'vars'.
    A list of non-negative integer types can be optionally  specified.
    List of variables and types must be of the same size and interval variable vars[i] will have type types[i]
    in the sequence variable.

    Args:
        vars:  List of IntervalVars that constitute the sequence.
        types: List of variable types as integers, same size as vars, or None (default).
        name:  Name of the sequence, None for automatic naming.
    Returns:
        IntervalVar expression.
    """
    return CpoSequenceVar(vars, types, name)


def transition_matrix(szvals, name=None):
    """ Creates a new transition matrix (square matrix of integers).

    A transition matrix is a square matrix of non-negative integers that represents a minimal distance between
    two interval variables.
    An instance of transition matrix can be used in the no_overlap constraint and in state functions.

      * In a no_overlap constraint the transition matrix represents the minimal distance between two
        non-overlapping interval variables.
        The matrix is indexed using the integer types of interval variables in the sequence variable
        of the no_overlap constraint.

      * In a state function, the transition matrix represents the minimal distance between two integer
        states of the function.

    A transition matrix can be created:

      * Deprecated.
        Giving only its size. In this case, a transition matrix is created by this constructor with all
        values initialized to zero. Matrix values can then be set using :meth:`set_value` method.

      * Giving the matrix values as a list of rows, each row being a list of integers.
        Matrix values can not be changed after it has been created.

    Args:
        szvals:  Matrix values expressed as a list of rows (iterable of iterables of positive integers).
        name (optional):  Name of the matrix. None by default.
    Returns:
        TransitionMatrix expression.
    """
    # Check build of editable matrix (deprecated)
    if is_int(szvals):
        return CpoTransitionMatrix(size=szvals, name=name)

    # Build matrix checking from cache
    res = build_cpo_transition_matrix(szvals)
    if name:
        res.set_name(name)
    return res


def tuple_set(tset, name=None):
    """ Create a tuple set.

    A tuple set is essentially a matrix of integers, but not necessarily square.
    Boolean expressions allowed_assignments() and forbidden_assignments() use a tuple set to express
    allowed/forbidden combinations of values for a collection of variables.
    Each allowed/forbidden combination is called a tuple and it is represented by a row in the tuple set matrix.

    Note that modeling methods allowed_assignments() and forbidden_assignments() automatically create a tuple_set
    object if given argument is an iterable of iterables.
    There is then no need to explicitly call this factory method to create a tuple set, except to assign a name to it.

    Args:
        tset:  List of tuples, as iterable of iterables of integers
        name:  Object name (default is None).
    Returns:
        TupleSet expression.
    """
    res = build_cpo_tupleset(tset)
    if name:
        res.set_name(name)
    return res


def state_function(trmtx=None, name=None):
    """ Create a new State Function

    Args:
        trmtx (optional): An optional transition matrix defining the transition distance between consecutive states
                          of the state function.
                          Transition matrix is given as a list of rows (iterable of iterables of positive integers),
                          or as the result of a call to the method :meth:`~docplex.cp.expression.transition_matrix`.
        name (optional):  Name of the state function
    Returns:
        CpoStateFunction expression
    """
    return CpoStateFunction(trmtx, name)


def is_cpo_expr(expr, type=None):
    """ Check if an expression is a CPO model expression

    Args:
        expr:             Value to check
        type (optional):  Precise CPO type, in Type_*
    Returns:
        True if parameter is a CPO expression, of the expected type if given
    """
    return isinstance(expr, CpoExpr) and (type is None or expr.type == type)


###############################################################################
##  Public Functions
###############################################################################

# Cache of CPO expressions corresponding to Python values
# This cache is used to retrieve the CPO expression that corresponds to a Python expression
# that is used multiple times in a model.
# This allows to:
#  - speed-up conversion as expression type has not to be recompute again
#  - reduce CPO file length as common expressions are easily identified.
_CACHE_CONTEXT = context.model.cache
_CPO_VALUES_FROM_PYTHON = ObjectCache(_CACHE_CONTEXT.size)
_CACHE_ACTIVE = _CACHE_CONTEXT.active

# Lock to protect the map
_CPO_VALUES_FROM_PYTHON_LOCK = threading.Lock()

def _convert_to_tuple_if_possible(val):
    try:
        return tuple(val)
    except TypeError:
        return val

def build_cpo_expr(val):
    """ Builds an expression from a given Python value.

    This method uses a cache to return the same CpoExpr for the same constant.

    Args:
        val: Value to convert (possibly already an expression).
    Returns:
        Corresponding expression.
    Raises:
        CpoException if conversion is not possible.
    """
    # Check if already a CPO expression
    vtyp = type(val)
    if issubclass(vtyp, CpoExpr):
        return val

    #  Check atoms (not cached)
    ctyp = _PYTHON_TO_CPO_TYPE.get(vtyp)
    if ctyp:
        return CpoValue(val, ctyp)

    # Check numpy scalars (special case when called from overloaded operator)
    if vtyp is NUMPY_NDARRAY and not val.shape:
        return CpoValue(val, _PYTHON_TO_CPO_TYPE.get(val.dtype.type))

    # Value is any type of array. Force it as a tuple
    try:
        val = tuple(val)
    except TypeError:
       raise CpoException("Impossible to build a CPO expression with value '{}' of type '{}'".format(to_string(val), type(val)))

    # Check if already in the cache
    if _CACHE_ACTIVE:
        with _CPO_VALUES_FROM_PYTHON_LOCK:
            try:
                cpval = _CPO_VALUES_FROM_PYTHON.get(val)
            except TypeError:
                # Convert to tuple every member of the tuple
                val = tuple(_convert_to_tuple_if_possible(x) for x in val)
                try:
                    cpval = _CPO_VALUES_FROM_PYTHON.get(val)
                except TypeError:
                    raise CpoException("Impossible to build a CPO expression with value '{}' of type '{}'".format(to_string(val), type(val)))
            if cpval is None:
                cpval = _create_cpo_array_expr(val)
                _CPO_VALUES_FROM_PYTHON.set(val, cpval)
    else:
        cpval = _create_cpo_array_expr(val)

    return cpval


def build_cpo_tupleset(val):
    """ Builds a TupleSet expression from a Python value.

    This method uses the value cache to return the same CpoExpr for the same value.

    Args:
        val: Value to convert. Iterator or iterators of integers, or existing TupleSet expression.
    Returns:
        Model tupleset, not editable.
    Raises:
        Exception if conversion is not possible.
    """
    # Check if already a TupleSet expression
    if isinstance(val, CpoExpr) and val.is_type(Type_TupleSet):
        return val

    # Create result set
    try:
        tset = tuple(tuple(x) for x in val)
    except TypeError:
        assert False, "Argument should be an iterable of iterables of integers."

    # Check if already in the cache
    if _CACHE_ACTIVE:
        with _CPO_VALUES_FROM_PYTHON_LOCK:
            key = ('tupleset', tset)
            cpval = _CPO_VALUES_FROM_PYTHON.get(key)
            if cpval is None:
                # Verify new tuple set
                assert len(tset) > 0, "Tuple set should not be empty"
                size = len(tset[0])
                assert all(len(t) == size for t in tset), "All tuples in 'tset' should have the same length"
                assert all(all(is_int(v) for v in r) for r in tset), "All tupleset values should be integer"
                # Put tuple set in cache
                cpval = CpoValue(tset, Type_TupleSet)
                _CPO_VALUES_FROM_PYTHON.set(key, cpval)
    else:
        cpval = CpoValue(tset, Type_TupleSet)

    return cpval


def build_cpo_transition_matrix(val):
    """ Builds a TransitionMatrix expression from a Python value.

    This method uses the value cache to return the same CpoExpr for the same value.

    Args:
        val: Value to convert. Iterator or iterators of integers, or existing TransitionMatrix expression.
    Returns:
        Model transition matrix, not editable.
    Raises:
        Exception if conversion is not possible.
    """
    # Check if already a TransitionMatrix expression
    if isinstance(val, CpoExpr) and val.is_type(Type_TransitionMatrix):
        return val

    # Create internal tuple
    try:
        trmx = tuple(tuple(x) for x in val)
    except TypeError:
        assert False, "Argument should be an iterable of iterables of integers."

    # Check if already in the cache
    if _CACHE_ACTIVE:
        with _CPO_VALUES_FROM_PYTHON_LOCK:
            key = ('matrix', trmx)
            cpval = _CPO_VALUES_FROM_PYTHON.get(key)
            if cpval is None:
                # Verify matrix
                size = len(trmx)
                assert size > 0, "Transition matrix should not be empty"
                assert all(len(t) == size for t in trmx), "All matrix lines should have the same length " + str(size)
                assert all(all(is_int(v) and v >= 0 for v in r) for r in trmx), "All matrix values should be positive integer"
                # Build matrix and put it in cache
                cpval = CpoTransitionMatrix(values=trmx)
                _CPO_VALUES_FROM_PYTHON.set(key, cpval)
    else:
        cpval = CpoTransitionMatrix(values=trmx)

    return cpval


def _create_cpo_array_expr(val):
    """ Create a new CP expression from a given array Python value

    Args:
        val: Origin value, supposedly NOT already CPO
    Returns:
        New expression
    Raises:
        CpoException if it is not possible.
    """
    # Value is any type of array. Force it as a tuple
    try:
        val = tuple(val)
    except TypeError:
       raise CpoException("Impossible to build a CPO expression with value '" + to_string(val) + "'")

    # Determine type
    typ = _get_cpo_array_type(val)
    if typ is None:
        raise CpoException("Impossible to build a CPO expression with value '" + to_string(val) + "'")

    # Convert array elements if required
    if typ.is_array_of_expr:
        return CpoValue(tuple(build_cpo_expr(v) for v in val), typ)

    # Default
    return CpoValue(val, typ)


def _create_cpo_expr(val):
    """ Create a new CP expression from a given Python value

    Args:
        val: Origin value, supposedly NOT already CPO
    Returns:
        New expression
    Raises:
        CpoException if it is not possible.
    """
    #  Check atom types
    vtyp = type(val)
    ctyp = _PYTHON_TO_CPO_TYPE.get(vtyp)
    if ctyp:
        return CpoValue(val, ctyp)

    # Check numpy Array Scalars (special case when called from overloaded operator)
    if vtyp is NUMPY_NDARRAY and not val.shape:
        return CpoValue(val, _PYTHON_TO_CPO_TYPE.get(val.dtype.type))

    # Value is any type of array.
    return _create_cpo_array_expr(val)


def _get_cpo_array_type(val):
    """ Determine the CPO type of a given Python array value
    Args:
        val: Python value
    Returns:
        Corresponding CPO Type, None if none
    """
    # Check empty Array
    if len(val) == 0:
        return Type_IntArray

    # Get the most common type for all array elements
    cet = None
    for v in val:
        # Determine type of element
        nt = _get_cpo_type(v)
        if nt is None:
            return None
        # Combine with global type
        ncet = nt if cet is None else cet.get_common_type(nt)
        if ncet is None:
            # Check special case of couple of int mixed with ints
            if cet is Type_Int:
                if (nt is Type_IntArray) and _is_cpo_int_interval(v):
                    ncet = Type_Int
                else:
                    return None
            elif cet is Type_IntArray:
                if nt is Type_Int:
                    ncet = Type_Int
                else:
                    return None
            else:
               return None
        cet = ncet

    # Determine array type for result element type
    if cet is Type_IntArray:
        if all(_is_cpo_int_interval(v) for v in val):
            return Type_IntArray
        else:
            return Type_TupleSet
    return cet.parent_array_type


def _get_cpo_type(val):
    """ Determine the CPO type of a given Python value
    Args:
        val: Python value
    Returns:
        Corresponding CPO Type, None if none
    """
    # Check simple types
    ctyp = _PYTHON_TO_CPO_TYPE.get(type(val))
    if ctyp:
        return ctyp

    # Check CPO Expr
    if isinstance(val, CpoExpr):
        return val.type

    # Check numpy Array Scalars (special case when called from overloaded operator)
    if type(val) is NUMPY_NDARRAY and not val.shape:
        return _PYTHON_TO_CPO_TYPE.get(val.dtype.type)

    # Check array
    if is_array(val):
        return _get_cpo_array_type(val)

    return None


def _clear_value_cache():
    """ Clear the cache of CPO values
    """
    with _CPO_VALUES_FROM_PYTHON_LOCK:
        _CPO_VALUES_FROM_PYTHON.clear()


def _get_cpo_type_str(val):
    """ Get the CPO type name of a value

    Args:
        val: Value
    Returns:
        Value type string in CPO types
    """
    return _get_cpo_type(val).get_name()


def _create_operation(oper, params):
    """ Create a new expression that matches an operation descriptor

    Search in the signatures which one matches a set or arguments
    and then create an instance of the returned expression

    Args:
        oper:   Operation descriptor
        params: List of expression parameters
    Returns:
        New expression 
    Raises:
        CpoException if no operation signature matches arguments
    """
    # assert isinstance(oper, CpoOperation)

    # Convert arguments in CPO expressions
    args = tuple(map(build_cpo_expr, params))
      
    # Search corresponding signature
    s = _get_matching_signature(oper, args)
    if s is None:
        raise CpoException("The combination of parameters ({}) is not allowed for operation '{}' ({})"
                           .format(", ".join(map(_get_cpo_type_str, args)), oper.python_name, oper.cpo_name))

    # Create result expression
    return CpoFunctionCall(s.operation, s.return_type, args)


###############################################################################
##  Private Functions
###############################################################################

# Mapping of Python types to CPO types
_PYTHON_TO_CPO_TYPE = {}
for t in BOOL_TYPES:
    _PYTHON_TO_CPO_TYPE[t] = Type_Bool
for t in INTEGER_TYPES:
    _PYTHON_TO_CPO_TYPE[t] = Type_Int
for t in FLOAT_TYPES:
    _PYTHON_TO_CPO_TYPE[t] = Type_Float
_PYTHON_TO_CPO_TYPE[CpoIntVar]           = Type_IntVar
_PYTHON_TO_CPO_TYPE[CpoIntervalVar]      = Type_IntervalVar
_PYTHON_TO_CPO_TYPE[CpoSequenceVar]      = Type_SequenceVar
_PYTHON_TO_CPO_TYPE[CpoTransitionMatrix] = Type_TransitionMatrix
_PYTHON_TO_CPO_TYPE[CpoStateFunction]    = Type_StateFunction


def _is_cpo_int(arg):
    """ Check that a value is a valid integer for cpo
    Args:
        val:  Value to check
    Returns:
        True if value is a valid CPO integer, False otherwise
    """
    return is_int(arg) and (INT_MIN <= arg <= INT_MAX)


def _is_cpo_int_interval(val):
    """ Check if a value represents an interval of CPO integers
    Args:
        val:  Value to check
    Returns:
        True if value is a tuple representing an interval of integers
    """
    return isinstance(val, tuple) and (len(val) == 2) and _is_cpo_int(val[0]) and _is_cpo_int(val[1]) and (val[1] >= val[0])


def _is_cpo_interval_value(arg):
    """ Check that a value is a valid value for an interval
    Args:
        val:  Value to check
    Returns:
        True if value is a valid interval, False otherwise
    """
    return is_int(arg) and (INTERVAL_MIN <= arg <= INTERVAL_MAX)


def _check_arg_boolean(arg, name):
    """ Check that an argument is a boolean and raise error if wrong
    Args:
        arg:  Argument value
        name: Argument name
    Returns:
        Boolean to be set
    Raises:
        Exception if argument has the wrong format
    """
    assert is_bool(arg), "Argument '{}' should be a boolean".format(name)
    return arg


def _check_arg_integer(arg, name):
    """ Check that an argument is an valid integer value and raises error if wrong
    Args:
        arg:  Argument value
        name: Argument name
    Returns:
        Integer to be set
    Raises:
        Exception if argument has the wrong format
    """
    assert is_int(arg) and (INT_MIN <= arg <= INT_MAX), "Argument '{}' should be an integer in [INT_MIN , INT_MAX]".format(name)
    return arg


def _check_arg_interval(arg, name):
    """ Check that an argument is an interval and raise error if wrong
    Args:
        arg:  Argument value
        name: Argument name
    Returns:
        Interval to be set
    Raises:
        Exception if argument has the wrong format
    """
    # Check default interval
    if arg is None:
        return DEFAULT_INTERVAL

    # Check single value
    if is_int(arg):
        assert INTERVAL_MIN <= arg <= INTERVAL_MAX, "Argument '{}' should be in [INTERVAL_MIN , INTERVAL_MAX]".format(name)
        return (arg, arg)

    assert isinstance(arg, (list, tuple)) and len(arg) == 2, "Argument '" + name + "' should be an integer or an interval expressed as a tuple of two integers"
    lb = arg[0]
    ub = arg[1]
    assert _is_cpo_interval_value(lb) and (INTERVAL_MIN <= lb <= INTERVAL_MAX, "Lower bound of argument '{}' should be an integer in [INTERVAL_MIN , INTERVAL_MAX]".format(name))
    assert _is_cpo_interval_value(ub) and (INTERVAL_MIN <= ub <= INTERVAL_MAX, "Upper bound of argument '{}' should be an integer in [INTERVAL_MIN , INTERVAL_MAX]".format(name))
    assert lb <= ub, "Lower bound or argument '{}' should be lower or equal to upper bound".format(name)
    return arg


def _build_int_var_domain(min, max, domain):
    """ Create/check integer variable domain from integer variable creation parameters
    Args:
        min:    Domain min value, None if extensive list.
        max:    Domain max value, None if extensive list.
        domain: Extensive list of values and/or intervals expressed as tuples of integers.
    Returns:
        Valid integer variable domain
    Raises:
        Exception if argument has the wrong format
    """
    # Domain not given extensively
    if domain is None:
        if min is None:
            if max is None:
                return ((INT_MIN, INT_MAX),)
            _check_arg_integer(max, "max")
            return ((INT_MIN, max),)
        else:
            if max is None:
                # Test that first argument is directly a domain (ascending compatibility)
                if is_array(min):
                    domain = min
                    min = None
                else:
                    _check_arg_integer(min, "min")
                    return ((min, INT_MAX),)
            else:
                _check_arg_integer(min, "min")
                _check_arg_integer(max, "max")
                assert min <= max, "Argument 'min' should be lower or equal to 'max'"
                return ((min, max),)

    # Domain given extensively
    assert (min is None) and (max is None), "If domain is given extensively in 'domain', 'min' and/or 'max' should not be given"
    assert is_array(domain), "Argument 'domain' should be a list of integers and/or intervals (tuples of 2 integers)"
    assert all(_is_cpo_int(v) or _is_cpo_int_interval(v) for v in domain), "Argument 'domain' should be a list of integers and/or intervals (tuples of 2 integers)"
    return domain


def _check_arg_step_function(arg, name):
    """ Check that an argument is a step function and raise error if wrong
    Args:
        arg:  Argument value
        name: Argument name
    Returns:
        Resulting step function
    Raises:
        Exception if argument has the wrong format
    """
    assert isinstance(arg, CpoExpr) and (arg.type == Type_StepFunction), "Argument '" + name + "' should be a StepFunction"
    return arg


def _check_arg_intensity(intensity, granularity):
    """ Check the intensity parameter of an interval var.
    Args:
       intensity:   Intensity function (None, or StepFunction).
       granularity: Granularity
    """
    if __debug__ and (intensity is not None):
        assert isinstance(intensity, CpoExpr) and (intensity.is_type(Type_StepFunction)), "Interval variable 'intensity' should be None or a StepFunction"
        if granularity is None:
            granularity = 100
        for (s, v) in intensity.get_step_list():
            assert is_int(s), "'intensity' step start should be an integer"
            assert is_int(v) and (v >= 0) and (v <= granularity), "'intensity' step value should be in [0..granularity]"


def _check_and_expand_interval_tuples(name, arr):
    """ Check that a list contains only integers and expand interval tuples if any
    Args:
        name:  Argument name
        arr:   Array of integers and/or intervals
    Returns:
        Array of integers
    Raises:
        Exception if wrong type
    """
    assert isinstance(arr, (list, tuple)), "Argument '{}' (type {}) should be a list of integers or intervals".format(name, type(arr))
    res = None
    for i in range(len(arr)):
        v = arr[i]
        if is_int(v):
            if res:
                res.append(v)
        else:
            assert _is_cpo_int_interval(v), "Argument '{}' (type {}) should be a list of integers or intervals".format(name, type(arr))
            if not res:
                res = list(arr[:i])
            res.extend(range(v[0], v[1] + 1))
    return tuple(res if res else arr)


def _get_matching_signature(oper, args):
    """ Search the first operation signature matched by a list of arguments

    Args:
        oper: Operation where searching signature
        args: Candidate list of argument expressions
    Returns:
        Matching signature, None if not found
    """
    # Search corresponding signature
    return next((s for s in oper.signatures if _is_matching_arguments(s, args)), None)


def _is_matching_arguments(sgn, args):
    """ Check if a list of argument expressions matches this signature

    Args:
        sgn:  Signature descriptor
        args: Candidate list of argument expressions
    Returns:
        True if the arguments are matching signature
    """
    for a, p in zip_longest(args, sgn.parameters):
        if a:
            # Accepted if there is a parameter descriptor that is compatible with argument type
            if not (p and a.type.is_kind_of(p.type)):
                return False
        else:
            # Argument absent, check that parameter has a default value
            if p.default_value is None:
                return False
    return True


def _is_equal_expressions(v1, v2):
    """ Check if two expressions can be considered as equivalent.

    This method handles values that can be CPO expressions, None, and manage possible
    differences between number representations.

    It is implemented outside expression objects and use a self-managed stack to avoid too many
    recursive calls that may lead to an exception 'RuntimeError: maximum recursion depth exceeded'.

    Args:
        v1:  First CPO expression
        v2:  Second CPO expression
    Returns:
        True if both values are 'equivalent'
    """
    # Initialize expression stack
    estack = [[v1, v2, -1]]  # [expr1, expr2, child index]

    # Loop while expression stack is not empty
    while estack:
        # Get expressions to compare
        edscr = estack[-1]
        v1, v2, cx = edscr

        # Check same object type
        if type(v1) != type(v2):
            return False

        # Check physical equality
        if v1 is v2:
            estack.pop()
            continue

        # Check if expression is a CPO expression
        if isinstance(v1, CpoExpr):
            # Check objects itself
            if (cx < 0) and not v1._equals(v2):
                return False
            # Access children
            ar1 = v1.children
            ar2 = v2.children
            # Check children
            alen = len(ar1)
            if (cx < 0) and (alen != len(ar2)):
                return False
            cx += 1
            if (cx >= alen):
                estack.pop()
                continue
            # Store new child index in descriptor
            edscr[2] = cx
            # Stack children to compare it
            estack.append([ar1[cx], ar2[cx], -1])

        # Else, expressions are Python values
        else:
            if not _is_equal_values(v1, v2):
                return False
            estack.pop()


    # Expressions identical
    return True


def _is_equal_values(v1, v2):
    """ Check if two values can be considered as equivalent.

    This method handles values that can be CPO expressions, None, and manage possible
    differences between number representations.

    Args:
        v1:  First value
        v2:  Second value
    Returns:
        True if both values are 'equivalent'
    """
    # Check obvious cases
    if v1 is v2:
        return True
    # Check specifically CPO expressions (to not call '==' operator on it)
    if isinstance(v1, CpoExpr):
        return v1.equals(v2)
    if isinstance(v2, CpoExpr):
        return False
    # Check floats
    if is_float(v1):
        return is_float(v2) and (abs(v1 - v2) <= _FLOATING_POINT_PRECISION * max(abs(v1), abs(v2)))
    if is_array(v1):
        return is_array(v2) and (len(v1) == len(v2)) and all(_is_equal_values(x1, x2) for x1, x2 in zip(v1, v2))
    if isinstance(v1, dict):
        return isinstance(v2, dict) and (len(v1) == len(v2)) and all(_is_equal_values(v1[k], v2[k]) for k in v1)
    # Check finally basic equality
    return v1 == v2


def _domain_iterator(d):
    """ Iterator on the individual values of an integer variable domain.

    Args:
        d: Domain to iterate
    Returns:
        Domain iterator
    """
    if isinstance(d, (list, tuple)):
        for x in d:
            if isinstance(x, (list, tuple)):
                min = x[0]
                max = x[1]
                if min == max:
                    yield min
                else:
                    for v in range(min, max + 1):
                        yield v
            else:
                yield x
    else:
        yield d


import docplex.cp.cpo_compiler as compiler
def _to_string(expr):
    """ Build a string representing an expression.

    Args:
        expr:  Expression to convert into string
    Returns:
        String representing this expression
    """
    return compiler.CpoCompiler(None)._compile_expression(expr)
