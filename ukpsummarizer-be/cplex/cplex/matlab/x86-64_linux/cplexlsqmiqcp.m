function [x,resnorm,residual,exitflag,output]=cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r,sostype,sosind,soswt,lb,ub,ctype,x0,options)
%%
% cplexlsqmiqcp
% Solve quadratically constrained mixed integer least squares problems.
%
% x = cplexlsqmiqcp(C,d,Aineq,bineq) solves the constrained mixed integer
% least squares problem min norm(C*x-d)^2 such that Aineq*x <= bineq.
%
% x = cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq) solves the preceding problem
% with the additional equality constraints Aeq*x = beq. If no inequalities
% exist, set Aineq=[] and bineq=[].
%
% x = cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r) solves the preceding
% problem while additionally satisfying the quadratic inequality
% constraints l*x + x'*Q*x <= r. If no equalities exist, set Aeq=[] 
% and beq=[].
%
% x = cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r,sostype,sosind,soswt)
% solves the preceding problem with the additional requirement that the SOS
% constraints are satisfied. If no quadratic inequalities exist, set l=[],
% Q=[] and r=[].
%
% x =
% cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r,sostype,sosind,soswt,lb,ub)
% defines a set of lower and upper bounds on the design variables, x, so
% that the solution is always in the range lb <= x <= ub. If no SOS
% constraints exist, set sostype=[], sosind=[] and soswt=[].
%
% x =
% cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r,sostype,sosind,soswt,lb,ub,ct
% ype) defines the types for each of the design variables. If no bounds
% exist, set lb=[] and ub=[].
%
% x =
% cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r,sostype,sosind,soswt,lb,ub,ct
% ype,x0) sets the starting point for the algorithm to x0. If all design
% variables are continuous, set ctype=[].
%
% x =
% cplexlsqmiqcp(C,d,Aineq,bineq,Aeq,beq,l,Q,r,sostype,sosind,soswt,lb,ub,ct
% ype,x0,options) minimizes with the default optimization options replaced
% by values in the structure options, which can be created using the
% function cplexoptimset. If you do not want to give an initial point, set
% x0=[].
%
% x = cplexlsqmiqcp(problem) where problem is a structure.
%
% [x,resnorm] = cplexlsqmiqcp(...) returns the value of the objective
% function at the solution x: resnorm = norm(C*x-d)^2.
%
% [x,resnorm,residual] = cplexlsqmiqcp(...) returns the residual at the
% solution: C*x-d.
%
% [x,resnorm,residual,exitflag] = cplexlsqmiqcp(...) returns a value
% exitflag that describes the exit condition of cplexlsqmiqcp.
%
% [x,resnorm,residual,exitflag,output] = cplexlsqmiqcp(...) returns a
% structure output that contains information about the optimization.
%
%  See also cplexoptimset
%

% ---------------------------------------------------------------------------
% File: cplexlsqmiqcp.m
% ---------------------------------------------------------------------------
% Licensed Materials - Property of IBM
% 5725-A06 5725-A29 5724-Y48 5724-Y49 5724-Y54 5724-Y55 5655-Y21
% Copyright IBM Corporation 2008, 2017. All Rights Reserved.
%
% US Government Users Restricted Rights - Use, duplication or
% disclosure restricted by GSA ADP Schedule Contract with
% IBM Corp.
% ---------------------------------------------------------------------------
