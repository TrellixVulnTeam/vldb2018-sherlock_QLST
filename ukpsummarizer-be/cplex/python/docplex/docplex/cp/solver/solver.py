# --------------------------------------------------------------------------
# Source file provided under Apache License, Version 2.0, January 2004,
# http://www.apache.org/licenses/
# (c) Copyright IBM Corp. 2015, 2016
# --------------------------------------------------------------------------
# Author: Olivier OUDOT, IBM Analytics, France Lab, Sophia-Antipolis

"""
This module implements appropriate software to solve a CPO model represented by a
:class:`docplex.cp.model.CpoModel` object.

It implements the following object classes:

 * :class:`CpoSolver` contains the public interface allowing to make solving requests with a model.
 * :class:`CpoSolverAgent` is an abstract class that is extended by the actual implementation(s) of
   the solving functions.

The :class:`CpoSolver` identifies and creates the required :class:`CpoSolverAgent` depending on the configuration
parameter *context.solver.agent' that contains the name of the agent to be used. This name is used to
access the configuration context *context.solver.<agent>* that contains the details about this agent.

For example, the default configuration refers to *docloud* as default solver agent, to solve model using *DOcplexcloud*
services. This means that at least following configuration elements must be set:
::

   context.solver.agent = 'docloud'
   context.solver.docloud.url = <URL of the service>
   context.solver.docloud.key = <Access key of the service>

The different methods that can be called on a CpoSolver object are:

 * :meth:`solve` simply solve the model and returns a solve result, if any.
   For convenience reason, this method is also directly available on the CpoModel object (:meth:`docplex.cp.model.CpoModel.solve`).
 * :meth:`search_next` and :meth:`end_search` allows to iterate on different solutions of the model.
 * :meth:`refine_conflict` calls the conflict refiner that identifies a minimal conflict for the infeasibility of
   the model.
 * :meth:`propagate` calls the propagation that communicates the domain reduction of a decision variable to
   all of the constraints that are stated over this variable.

Except :meth:`solve`, these functions are only available with a local solver with release greater or equal to 12.7.0.
When a method is not available, an exception *CpoNotSupportedException* is raised.

If the methods :meth:`search_next` and :meth:`end_search` are available in the underlying solver agent,
the :class:`CpoSolver` object acts as an iterator. All solutions are retrieved using a loop like:
::

   solver = CpoSolver(mdl)
   for sol in solver:
       sol.print_solution()

A such solution iteration can be interrupted at any time by calling end_search() that returns
a fail solution including the last solve status.


Detailed description
--------------------
"""

import docplex.cp.config as config
from docplex.cp.utils import CpoException, CpoNotSupportedException, make_directories, Context, is_array, is_string, parse_json_string
import docplex.cp.utils as utils
from docplex.cp.cpo_compiler import CpoCompiler
import docplex.cp.solver.environment_client as runenv
from docplex.cp.solution import *
from docplex.cp.solver.solver_listener import CpoSolverListener

import time, importlib, inspect
import traceback
import threading

###############################################################################
##  Public constants
###############################################################################

# Solver statuses
STATUS_IDLE              = "Idle"             # Solver created but inactive
STATUS_RELEASED          = "Released"         # Solver stopped with resources released.
STATUS_ABORTED           = "Aborted"          # Solver has been aborted.
STATUS_SOLVING           = "SolveRunning"     # Simple solve in progress
STATUS_SEARCH_WAITING    = "SearchWaiting"    # Search started or waiting to call next
STATUS_SEARCH_RUNNING    = "NextRunning"      # Search of next solution in progress
STATUS_REFINING_CONFLICT = "RefiningConflict" # Solver refine conflict in progress
STATUS_PROPAGATING       = "Propagating"      # Propagation in progress
STATUS_RUNNING_SEEDS     = "RunningSeeds"     # Run seeds in progress

# Set of statuses that end solver
_ENDING_STATUSES = frozenset((STATUS_RELEASED, STATUS_ABORTED))


###############################################################################
##  Public classes
###############################################################################

class CpoSolverAgent(object):
    """ This class is an abstract class that must be extended by every solver agent that intend
    to be called by :class:`CpoSolver` to solve a CPO model.
    """

    def __init__(self, solver, params, context):
        """ Constructor

        Args:
            solver:   Parent solver
            params:   Solving parameters
            context:  Solver agent context
        Raises:
            CpoException if jar file does not exists
        """
        super(CpoSolverAgent, self).__init__()
        self.solver = solver             # Parent solver
        self.model = solver.get_model()  # Source model
        self.params = params             # Model parameters
        self.context = context           # Solve context
        self.last_json_result = None     # Last result
        self.log_data = []               # Log data (list of strings)
        self.rename_map = None           # Map of renamed variables. Key is new name, value is original name
        self.process_infos = CpoProcessInfos()

        # Initialize log
        self.log_output = context.get_log_output()                            # Log output stream
        self.log_print = context.trace_log and (self.log_output is not None)  # Print log indicator
        self.log_buffer = [] if context.add_log_to_solution else None         # Log buffer
        self.log_enabled = self.log_print or (self.log_data is not None)      # Global log process indicator


    def solve(self):
        """ Solve the model

        Returns:
            Model solve result, object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def start_search(self):
        """ Start a new search. Solutions are retrieved using method search_next().

        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def search_next(self):
        """ Search the next available solution.

        Returns:
            Next solve result,
            object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def end_search(self):
        """ End current search.

        Returns:
            Last (fail) solve result with last solve information,
            object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def refine_conflict(self):
        """ This method identifies a minimal conflict for the infeasibility of the current model.

        Given an infeasible model, the conflict refiner can identify conflicting constraints and variable domains
        within the model to help you identify the causes of the infeasibility.
        In this context, a conflict is a subset of the constraints and/or variable domains of the model
        which are mutually contradictory.
        Since the conflict is minimal, removal of any one of these constraints will remove that
        particular cause for infeasibility.
        There may be other conflicts in the model; consequently, repair of a given conflict
        does not guarantee feasibility of the remaining model.

        Returns:
            Conflict result,
            object of class :class:`~docplex.cp.solution.CpoRefineConflictResult`.
        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def propagate(self):
        """ This method invokes the propagation on the current model.

        Constraint propagation is the process of communicating the domain reduction of a decision variable to
        all of the constraints that are stated over this variable.
        This process can result in more domain reductions.
        These domain reductions, in turn, are communicated to the appropriate constraints.
        This process continues until no more variable domains can be reduced or when a domain becomes empty
        and a failure occurs.
        An empty domain during the initial constraint propagation means that the model has no solution.

        The result is a object of class CpoSolveResult, the same than the one returned by solve() method.
        However, in this case, variable domains may not be completely defined.

        Returns:
            Propagation result,
            object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def run_seeds(self, nbrun):
        """ This method runs *nbrun* times the CP optimizer search with different random seeds
        and computes statistics from the result of these runs.

        Result statistics are displayed on the log output that should be activated.
        If the appropriate configuration variable *context.solver.add_log_to_solution* is set to True (default),
        log is also available in the *CpoRunResult* result object, accessible as a string using the method
        :meth:`~docplex.cp.solution.CpoRunResult.get_solver_log`

        Each run of the solver is stopped according to single solve conditions (TimeLimit for example).
        Total run time is then expected to take *nbruns* times the duration of a single run.

        Args:
            nbrun: Number of runs with different seeds.
        Returns:
            Run result, object of class :class:`~docplex.cp.solution.CpoRunResult`.
        Raises:
            CpoNotSupportedException: method not available in this solver agent.
        """
        self._raise_not_supported()


    def end(self):
        """ End solver agent and release all resources.
        """
        self.solver = None
        self.model = None
        self.params = None
        self.context = None


    def _get_cpo_model_string(self):
        """ Get the CPO model as a string, according to configuration

        Return:
            String containing the CPO model in CPO file format
        """
        # Build string
        ctx = self.context
        stime = time.time()
        cplr = CpoCompiler(self.model, params=self.params, context=self.context.get_root())
        cpostr = cplr.get_as_string()
        self.rename_map = cplr.get_rename_map()
        self.process_infos[CpoProcessInfos.MODEL_COMPILE_TIME] = time.time() - stime
        self.process_infos[CpoProcessInfos.MODEL_DATA_SIZE] = len(cpostr)

        # Trace CPO model if required
        lout = ctx.get_log_output()
        if lout and ctx.trace_cpo:
            stime = time.time()
            lout.write("Model '" + str(self.model.get_name()) + "' in CPO format:\n")
            lout.write(cpostr)
            lout.write("\n")
            self.model.print_information(lout)
            lout.write("\n")
            lout.flush()
            self.process_infos.incr(CpoProcessInfos.MODEL_DUMP_TIME, time.time() - stime)

        # Dump in dump directory if required
        if ctx.model.dump_directory:
            stime = time.time()
            make_directories(ctx.model.dump_directory)
            mname = self.model.get_name()
            if mname is None:
                mname = "Anonymous"
            file = ctx.model.dump_directory + "/" + mname + ".cpo"
            with utils.open_utf8(file, 'w') as f:
                f.write(cpostr)
            self.process_infos.incr(CpoProcessInfos.MODEL_DUMP_TIME, time.time() - stime)

        # Return
        return cpostr


    def _add_log_data(self, data):
        """ Add new log data
        Args:
            data:  Data to log (String)
        """
        self.solver._notify_new_log(data)
        if self.log_enabled:
            if self.log_print:
                self.log_output.write(data)
                self.log_output.flush()
            if self.log_buffer is not None:
                self.log_buffer.append(data)


    def _set_last_json_result_string(self, json):
        """ Set the string containing last received JSON result

        Args:
            json: JSON result string
        """
        self.context.log(3, "JSON result:\n", json)
        self.last_json_result = json


    def _get_last_json_result_string(self):
        """ Get the string containing last received JSON result

        Return:
            Last JSON result string, None if none
        """
        return self.last_json_result


    def _create_result_object(self, rclass, jsol=None):
        """ Create a new result object and fill it with necessary data
        Args:
            rclass:            Result object class
            jsol (optional):   JSON solution string
        Returns:
            New result object preinitialized
        """
        res = rclass(self.model)
        res.process_infos.update(self.process_infos)

        # Process JSON solution
        self.context.log(3, "JSON result:\n", jsol)
        self.last_json_result = jsol

        # Parse JSON solution
        if jsol:
            # Parse JSON
            stime = time.time()
            jsol = parse_json_string(jsol)
            # Replace variable names if rename was used
            if self.rename_map:
                _replace_names_in_json_dict(jsol.get('intVars'),        self.rename_map)
                _replace_names_in_json_dict(jsol.get('intervalVars'),   self.rename_map)
                _replace_names_in_json_dict(jsol.get('sequenceVars'),   self.rename_map)
                _replace_names_in_json_dict(jsol.get('stateFunctions'), self.rename_map)
                self.context.log(3, "Updated JSON result:\n", jsol)
            # Build result structure
            res._add_json_solution(jsol)
            res.process_infos[CpoProcessInfos.RESULT_PARSE_TIME] = time.time() - stime

        # Process Log
        if self.log_buffer is not None:
            res._set_solver_log(''.join(self.log_buffer))
            self.log_buffer = []
        return res


    def _raise_not_supported(self):
        """ Raise an exception indicating that the calling method is not supported.
        """
        raise CpoNotSupportedException("Method '{}' is not available in solver agent '{}' ({})."
                                       .format(inspect.stack()[1][3], self.context.agent, type(self)))


class CpoSolver(object):
    """ This class represents the public API of the object allowing to solve a CPO model.

    It create the appropriate :class:`CpoSolverAgent` that actually implements solving functions, depending
    on the value of the configuration parameter *context.solver.agent*.
    """
    __slots__ = ('model',  # Model to solve
                 'context',  # Solving context
                 'agent',  # Solver agent
                 'status',  # Current solver status
                 'last_result',  # Last returned solution
                 'listeners',  # List of solve listeners
                 'status_lock', # Lock protecting status change
                )

    def __init__(self, model, **kwargs):
        """ Constructor

        All necessary solving parameters are taken from the solving context that is constructed from the following list
        of sources, each one overwriting the previous:

           - the parameters that are set in the model itself,
           - the default solving context that is defined in the module :mod:`~docplex.cp.config`
           - the user-specific customizations of the context that may be defined (see :mod:`~docplex.cp.config` for details),
           - the optional arguments of this method.

        Args:
            context (Optional): Complete solving context.
                                If not given, solving context is the default one that is defined in the module
                                :mod:`~docplex.cp.config`.
            params (Optional):  Solving parameters (object of class :class:`~docplex.cp.parameters.CpoParameters`)
                                that overwrite those in the solving context.
            url (Optional):     URL of the DOcplexcloud service that overwrites the one defined in the solving context.
            key (Optional):     Authentication key of the DOcplexcloud service that overwrites the one defined in
                                the solving context.
            (param) (Optional): Any individual solving parameter as defined in class :class:`~docplex.cp.parameters.CpoParameters`
                               (for example *TimeLimit*, *Workers*, *SearchType*, etc).
            (others) (Optional): Any leaf attribute with the same name in the solving context
                                (for example *agent*, *trace_log*, *trace_cpo*, etc).
            (listeners) (Optional): List of solution listeners
        """
        super(CpoSolver, self).__init__()
        self.agent = None
        self.last_result = None
        self.status = STATUS_IDLE
        self.status_lock = threading.Lock()
        self.listeners = []

        # Build effective context from args
        context = config._get_effective_context(**kwargs)

        # If defined, limit the number of threads
        mxt = context.solver.max_threads
        if isinstance(mxt, int):
            # Maximize number of workers
            nbw = context.params.Workers
            if (nbw is None) or (nbw > mxt):
                context.params.Workers = mxt
                print("WARNING: Number of workers has been reduced to " + str(mxt) + " to comply with platform limitations.")

        # Save attributes
        self.model = model
        self.context = context

        # Determine appropriate solver agent
        self.agent = self._get_solver_agent()

        # Add solver listener for environment
        env = runenv.get_environment()
        if env is not None:
            self.add_listener(runenv.EnvSolverListener())


    def __iter__(self):
        """  Define solver as an iterator """
        return self


    def __del__(self):
        # End solver
        self.end()


    def __enter__(self):
        # For usage in with
        return self


    def __exit__(self, exception_type, exception_value, traceback):
        # End solver
        self.end()


    def get_model(self):
        """ Returns the model solved by this solver.

        Returns:
            Model solved by this solver
        """
        return self.model


    def solve(self):
        """ Solve the model

        This function solves the model using CP Optimizer's built-in strategy.
        The built-in strategy is determined by setting the parameter SearchType (see docplex.cp.parameters).
        If the model contains an objective, then the optimal solution with respect to the objective will be calculated.
        Otherwise, a solution satisfying all problem constraints will be calculated.

        The function returns an object of the class CpoSolveResult (see docplex.cp.solution) that contains the solution
        if exists, plus different information on the solving process.

        If the context parameter *solve_with_start_next* (or config parameter *context.solver.solve_with_start_next*)
        is set to True, the call to solve() is replaced by loop start/next which returns the last solution found.
        If a solver listener has been added to the solver, it is warned of all intermediate solutions.

        Returns:
            Solve result, object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoException: (or derived) if error.
        """
        # Check solve with start/next
        if self.context.solver.solve_with_start_next:
            return self._solve_with_start_next()

        # Notify listeners
        for lstnr in self.listeners:
            lstnr.start_solve(self)

        # Solve model
        stime = time.time()
        self._set_status(STATUS_SOLVING)
        try:
            msol = self.agent.solve()
        except Exception as e:
            if self.status == STATUS_ABORTED:
                # Search has been aborted externally
                for lstnr in self.listeners:
                    lstnr.end_solve(self)
                self._set_status(STATUS_RELEASED)
                return self._create_solution_aborted()
            else:
                traceback.print_exc()
                raise e
        self._set_status(STATUS_IDLE)
        stime = time.time() - stime
        self.context.solver.log(1, "Model '", self.model.get_name(), "' solved in ", round(stime, 2), " sec.")
        msol.process_infos[CpoProcessInfos.SOLVE_TOTAL_TIME] = stime

        # Set solve time in solution if not done
        if msol.get_solve_time() == 0:
            msol._set_solve_time(stime)

        # Store last solution
        self.last_result = msol

        # Notify listeners
        for lstnr in self.listeners:
            lstnr.result_found(self, msol)
            lstnr.end_solve(self)

        # Return solution
        return msol
        
     
    def search_next(self):
        """ Get the next available solution.

        This function is available only with local CPO solver with release number greater or equal to 12.7.0.

        Returns:
            Next model solution,
            object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: if method not available in the solver agent.
        """
        # Initiate search if needed
        if self.status == STATUS_IDLE:
            # Notify listeners about start of search
            self.agent.start_search()
            self._set_status(STATUS_SEARCH_WAITING)
            for lstnr in self.listeners:
                lstnr.start_solve(self)
        # Check if status is aborted (may be caused by listener)
        if self.status == STATUS_ABORTED:
            for lstnr in self.listeners:
                lstnr.end_solve(self)
            self._set_status(STATUS_RELEASED)
            self.last_result = self._create_solution_aborted()
            return self.last_result
        else:
            self._check_status(STATUS_SEARCH_WAITING)

        # Solve model
        stime = time.time()
        self._set_status(STATUS_SEARCH_RUNNING)
        try:
            msol = self.agent.search_next()
        except BaseException as e:
            sys.stdout.flush()
            if self.status == STATUS_ABORTED:
                # Search has been aborted externally
                for lstnr in self.listeners:
                    lstnr.end_solve(self)
                self._set_status(STATUS_RELEASED)
                self.last_result = self._create_solution_aborted()
                return self.last_result
            else:
                #traceback.print_exc()
                raise e
        self._set_status(STATUS_SEARCH_WAITING)
        stime = time.time() - stime
        self.context.solver.log(1, "Model '", self.model.get_name(), "' next solution in ", round(stime, 2), " sec.")

        # Set solve time in solution if not done
        if msol.get_solve_time() == 0:
            msol._set_solve_time(stime)

        # Store last solution
        self.last_result = msol

        # Notify listeners
        for lstnr in self.listeners:
            lstnr.result_found(self, msol)

        # Return solution
        return msol


    def end_search(self):
        """ End current search.

        This function is available only with local CPO solver with release number greater or equal to 12.7.0.

        Returns:
            Last (fail) model solution with last solve information,
            object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: if method not available in the solver agent.
        """
        if self.status == STATUS_RELEASED:
           return self.last_result
        self._check_status(STATUS_SEARCH_WAITING)
        msol = self.agent.end_search()
        self._set_status(STATUS_IDLE)
        self.last_result = msol
        for lstnr in self.listeners:
            lstnr.end_solve(self)
        return msol


    def refine_conflict(self):
        """ This method identifies a minimal conflict for the infeasibility of the current model.

        Given an infeasible model, the conflict refiner can identify conflicting constraints and variable domains
        within the model to help you identify the causes of the infeasibility.
        In this context, a conflict is a subset of the constraints and/or variable domains of the model
        which are mutually contradictory.
        Since the conflict is minimal, removal of any one of these constraints will remove that
        particular cause for infeasibility.
        There may be other conflicts in the model; consequently, repair of a given conflict
        does not guarantee feasibility of the remaining model.

        Conflict refiner is controled by the following parameters (that can be set at CpoSolver creation):

         * ConflictRefinerBranchLimit
         * ConflictRefinerFailLimit
         * ConflictRefinerIterationLimit
         * ConflictRefinerOnVariables
         * ConflictRefinerTimeLimit

        that are described in module :mod:`docplex.cp.parameters`.

        Note that the general *TimeLimit* parameter is used as a limiter for each conflict refiner iteration, but the
        global limitation in time must be set using *ConflictRefinerTimeLimit* that is infinite by default.

        This function is available only with local CPO solver with release number greater or equal to 12.7.0.

        Returns:
            List of constraints that cause the conflict,
            object of class :class:`~docplex.cp.solution.CpoRefineConflictResult`.
        Raises:
            CpoNotSupportedException: if method not available in the solver agent.
        """
        self._check_status(STATUS_IDLE)
        self._set_status(STATUS_REFINING_CONFLICT)
        msol = self.agent.refine_conflict()
        self._set_status(STATUS_IDLE)
        return msol


    def propagate(self):
        """ This method invokes the propagation on the current model.

        Constraint propagation is the process of communicating the domain reduction of a decision variable to
        all of the constraints that are stated over this variable.
        This process can result in more domain reductions.
        These domain reductions, in turn, are communicated to the appropriate constraints.
        This process continues until no more variable domains can be reduced or when a domain becomes empty
        and a failure occurs.
        An empty domain during the initial constraint propagation means that the model has no solution.

        The result is a object of class CpoSolveResult, the same than the one returned by solve() method.
        However, variable domains may not be completely defined.

        This function is available only with local CPO solver with release number greater or equal to 12.7.0.

        Returns:
            Propagation result, object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        Raises:
            CpoNotSupportedException: method not available in configured solver agent.
        """
        self._check_status(STATUS_IDLE)
        self._set_status(STATUS_PROPAGATING)
        psol = self.agent.propagate()
        self._set_status(STATUS_IDLE)
        return psol


    def run_seeds(self, nbrun):
        """ This method runs *nbrun* times the CP optimizer search with different random seeds
        and computes statistics from the result of these runs.

        Result statistics are displayed on the log output that should be activated.
        If the appropriate configuration variable *context.solver.add_log_to_solution* is set to True (default),
        log is also available in the *CpoRunResult* result object, accessible as a string using the method
        :meth:`~docplex.cp.solution.CpoRunResult.get_solver_log`

        Each run of the solver is stopped according to single solve conditions (TimeLimit for example).
        Total run time is then expected to take *nbruns* times the duration of a single run.

        Args:
            nbrun: Number of runs with different seeds.
        Returns:
            Run result, object of class :class:`~docplex.cp.solution.CpoRunResult`.
        Raises:
            CpoNotSupportedException: method not available in configured solver agent.
        """
        self._check_status(STATUS_IDLE)
        self._set_status(STATUS_RUNNING_SEEDS)
        rsol = self.agent.run_seeds(nbrun)
        self._set_status(STATUS_IDLE)
        return rsol


    def get_last_solution(self):
        """ Get the last result returned by this solver

        DEPRECATED. Use get_last_result instead.

        Returns:
            Solve result, object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        """
        return self.last_result


    def get_last_result(self):
        """ Get the last result returned by this solver

        Returns:
            Solve result, object of class :class:`~docplex.cp.solution.CpoSolveResult`.
        """
        return self.last_result


    def abort_search(self):
        # Abort current search if any. Temporarily, end the process
        self._set_status(STATUS_ABORTED)
        agt = self.agent
        self.agent = None
        if (agt is not None):
            agt.end()


    def end(self):
        # End this solver and release associated resources
        agt = self.agent
        self.agent = None
        self._set_status(STATUS_RELEASED)
        if (agt is not None):
            agt.end()


    def next(self):
        """ For solution iteration, get the next available solution.

        This function is available only with local CPO solver with release number greater or equal to 12.7.0.

        Returns:
            Next model solution (object of class :class:`~docplex.cp.solution.CpoModelSolution`)
        """
        # Get next solution
        msol = self.search_next()
        if msol:
            return msol
        self.end_search()
        raise StopIteration()


    def __next__(self):
        """ Get the next available solution (same as next() for compatibility with Python 3)

        This function is available only with local CPO solver with release number greater or equal to 12.7.0.

        Returns:
            Next model solution (object of class CpoModelSolution)
        """
        return self.next()


    def add_listener(self, lstnr):
        """ Add a solver listener.

        A solver listener is an object extending the class :class:`~docplex.cp.solver.solver_listener.CpoSolverListener`
        which provides multiple functions that are called to notify about the different solving steps.

        Args:
            lstnr:  Solver listener
        """
        assert isinstance(lstnr, CpoSolverListener), \
            "Listener should be an object of class docplex.cp.solver.solver_listener.CpoSolverListener"
        self.listeners.append(lstnr)
        # Notify listener
        lstnr.solver_created(self)


    def remove_listener(self, lstnr):
        """ Remove a solver listener previously added with :meth:`~docplex.cp.solver.solver.CpoSolver.add_listener`.

        Args:
            lstnr:  Listener to remove.
        """
        self.listeners.remove(lstnr)


    def _set_status(self, status):
        """ Change solve status, only if allowed

        Args:
            status: New solve status
        """
        with self.status_lock:
            if (status in _ENDING_STATUSES) or (not self.status in _ENDING_STATUSES):
                self.status = status


    def _notify_new_log(self, data):
        """ Notify new log data (called by agent)

        Args:
            data: Log data as a string
        """
        # Notify listeners
        for lstnr in self.listeners:
            lstnr.new_log_data(self, data)


    def _solve_with_start_next(self):
        """ Solve the model using a start/next loop instead of standard solve.

        Raise:
            Last model solution
        """
        last_sol = None
        while True:
            # Search for next solution
            msol = self.search_next()

            # Check successful search
            if msol:
                last_sol = msol
            else:
                if last_sol is None:
                    return msol
                # Merge last valid solution with last solve infos
                last_sol.solver_infos = msol.solver_infos
                return last_sol


    def _check_status(self, ests):
        """ Throws an exception if solver status is not the expected one

        Args:
            ests:  Expected status, or list of expected statuses
        Raise:
            CpoException if solver is not in the right status
        """
        if (self.status != ests):
           raise CpoException("Unexpected solver status. Should be '{}' instead of '{}'".format(ests, self.status))


    def _create_solution_aborted(self):
        """ Create an empty solution with aborted status
        """
        res = CpoSolveResult(self.model)
        res.solve_status = SOLVE_STATUS_JOB_ABORTED
        res.fail_status = FAIL_STATUS_ABORT
        res.search_status = SEARCH_STATUS_STOPPED
        res.stop_cause = STOP_CAUSE_ABORT
        return res


    def _get_solver_agent(self):
        """ Get the solver agent instance that is used to solve the model.

        Returns:
            Solver agent instance
        Raises:
            CpoException:  Agent creation error
        """
        # Determine selectable agent(s)
        sctx = self.context.solver

        alist = sctx.agent
        if alist is None:
            alist = 'docloud'
        elif not (is_string(alist) or is_array(alist)):
            raise CpoException("Agent identifier in config.context.solver.agent should be a string or a list of strings.")

        # Create agent
        if is_string(alist):
            aname = alist
            agent = self._create_solver_agent(alist)
        else:
            # Search first available agent in the list
            agent = None
            errors = []
            for aname in alist:
                try:
                    agent = self._create_solver_agent(aname)
                    break
                except Exception as e:
                    errors.append((aname, str(e)))
                # Agent not found
                errstr = ', '.join(a + ": " + str(e) for (a, e) in errors)
                raise CpoException("Agent creation error: " + errstr)

        # Log solver agent
        sctx.log(1, "Solve model '", self.model.get_name(), "' with agent '", aname, "'")
        agent.process_infos[CpoProcessInfos.SOLVER_AGENT] = aname
        return agent


    def _create_solver_agent(self, aname):
        """ Create a new solver agent from its name.

        Args:
            name: Name of the agent
        Returns:
            Solver agent instance
        Raises:
            CpoException: Agent creation error
        """
        # Get agent context
        sctx = self.context.solver.get(aname)
        if not isinstance(sctx, Context):
            raise CpoException("Unknown solving agent '" + aname + "'. Check config.context.solver.agent parameter.")
        if sctx.is_log_enabled(3):
            sctx.log(3, "Context for solving agent '", aname, "':")
            sctx.print_context(out=sctx.get_log_output())
        cpath = sctx.class_name
        if cpath is None:
            raise CpoException("Solving agent '" + aname + "' context does not contain attribute 'class_name'")

        # Split class name
        pnx = cpath.rfind('.')
        if pnx < 0:
            raise CpoException("Invalid class name '" + cpath + "' for solving agent '" + aname + "'. Should be <package>.<module>.<class>.")
        mname = cpath[:pnx]
        cname = cpath[pnx + 1:]

        # Load module
        try:
            module = importlib.import_module(mname)
        except Exception as e:
            raise CpoException("Module '" + mname + "' import error: " + str(e))

        # Create and check class
        sclass = getattr(module, cname, None)
        if sclass is None:
            raise CpoException("Module '" + mname + "' does not contain a class '" + cname + "'")
        if not inspect.isclass(sclass):
            raise CpoException("Agent class '" + cpath + "' is not a class.")
        if not issubclass(sclass, CpoSolverAgent):
            raise CpoException("Solver agent class '" + cpath + "' does not extend CpoSolverAgent.")

        # Create agent instance
        agent = sclass(self, sctx.params, sctx)
        return agent


###############################################################################
##  Private Functions
###############################################################################

def _get_solver_agent_class(aname, sctx):
    """ Get a solver agent class from its name

    Args:
        aname:  Solver agent name
        sctx:   Candidate solver context
    Returns:
        Solver agent class
    """
    # Check for solver agent context
    if not isinstance(sctx, Context):
        raise CpoException("Unknown solving agent '" + aname + "'. Check config.context.solver.agent parameter.")
    cpath = sctx.class_name
    if cpath is None:
        raise CpoException("Solving agent '" + aname + "' context does not contain attribute 'class_name'")

    # Split class name
    pnx = cpath.rfind('.')
    if pnx < 0:
        raise CpoException("Invalid class name '" + cpath + "' for solving agent '" + aname + "'. Should be <package>.<module>.<class>.")
    mname = cpath[:pnx]
    cname = cpath[pnx + 1:]

    # Load module
    try:
        module = importlib.import_module(mname)
    except Exception as e:
        raise CpoException("Module '" + mname + "' import error: " + str(e))

    # Create and check class
    sclass = getattr(module, cname, None)
    if sclass is None:
        raise CpoException("Module '" + mname + "' does not contain a class '" + cname + "'")
    if not inspect.isclass(sclass):
        raise CpoException("Agent class '" + cpath + "' is not a class.")
    if not issubclass(sclass, CpoSolverAgent):
        raise CpoException("Solver agent class '" + cpath + "' does not extend CpoSolverAgent.")

    # Return
    return sclass

def _replace_names_in_json_dict(jdict, renmap):
    """ Replace keys that has been renamed in a JSON result directory
    Args:
        jdict:  Json result dictionary
        renmap: Renaming map, key is name to replace, value is name to use instead
    """
    if jdict:
        for k in list(jdict.keys()):
            nk = renmap.get(k)
            if nk:
                jdict[nk] = jdict[k]
                del jdict[k]

