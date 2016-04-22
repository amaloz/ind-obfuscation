from __future__ import print_function

from pyobf.bp import AbstractBranchingProgram, Layer
from pyobf.circuit import ParseException

import numpy as np
from numpy import matrix
# from sage.all import matrix

import json, random, sys

def transpose(bps):
    bps.reverse()
    newbps = []
    for bp in bps:
        newbps.append(Layer(bp.inp, bp.zero.transpose(), bp.one.transpose(),
                            bp.zeroset, bp.oneset))
    return newbps

def augment(bps, r):
    def _augment(M, r):
        nrows, ncols = M.shape
        Z_1 = np.zeros([nrows, r], int)
        Z_2 = np.zeros([r, ncols], int)
        I_r = np.identity(r, int)
        tmp1 = np.concatenate((M, Z_1), 1).transpose()
        tmp2 = np.concatenate((Z_2, I_r), 1).transpose()
        return np.concatenate((tmp1, tmp2), 1).transpose()
        # Z_1 = matrix.zero(nrows, r)
        # Z_2 = matrix.zero(r, ncols)
        # I_r = matrix.identity(r)
        # tmp1 = M.augment(Z_1).transpose()
        # tmp2 = Z_2.augment(I_r).transpose()
        # return tmp1.augment(tmp2).transpose()
    newbps = []
    for bp in bps:
        newbps.append(Layer(bp.inp, _augment(bp.zero, r), _augment(bp.one, r),
                            bp.zeroset, bp.oneset))
    return newbps

def mult_left(bps, m):
    bps[0] = bps[0].mult_left(m)
def mult_right(bps, m):
    bps[-1] = bps[-1].mult_right(m)

class SZBranchingProgram(AbstractBranchingProgram):
    def __init__(self, fname, verbose=False, obliviate=False, formula=True):
        super(SZBranchingProgram, self).__init__(verbose=verbose)
        if formula:
            self.bp = self._load_formula(fname)
        else:
            self.bp = self._load_bp(fname)

    def obliviate(self):
        assert self.ninputs and self.depth
        newbp = []
        for m in self.bp:
            for i in xrange(self.ninputs):
                if m.inp == i:
                    newbp.append(m)
                else:
                    newbp.append(Layer(i, self.zero, self.zero))
        self.bp = newbp

    def _load_bp(self, fname):
        bp = []
        try:
            with open(fname) as f:
                for line in f:
                    if line.startswith('#'):
                        continue
                    bp_json = json.loads(line)
                    for step in bp_json['steps']:
                        bp.append(
                            Layer(int(step['position']), matrix(step['0']), matrix(step['1'])))

                    assert len(bp_json['outputs'])    == 1 and \
                           len(bp_json['outputs'][0]) == 2
                    first_out = bp_json['outputs'][0][0].lower()
                    if first_out not in ['false', '0']:
                        if first_out not in ['true', '1']:
                            print('warning: interpreting %s as a truthy output' % first_out)
                        bp[-1].zero.swap_columns(0,1)
                        bp[-1].one .swap_columns(0,1)
                    return bp
        except IOError as e:
            print(e)
            sys.exit(1)
        except ValueError as e:
            print('expected numeric position while parsing branching program JSON')
            print(e)
            sys.exit(1)

    def _load_formula(self, fname):
        def _new_gate(num):
            zero = matrix([1, 0])
            one = matrix([1, 1])
            return [Layer(num, zero, one)]
        def _two_input_gate(bp0, bp1, left, right):
            bp1 = augment(transpose(bp1), 1)
            mult_left(bp1, left)
            mult_right(bp1, right)
            bp0.extend(bp1)
            return bp0
        def _and_gate(num, bp0, bp1):
            left = matrix([[0, 0, 1], [0, 1, 0]])
            right = matrix([[0, 1], [1, 0]])
            return _two_input_gate(bp0, bp1, left, right)
        def _id_gate(num, bp0):
            right = matrix([[1, 0], [0, 1]])
            mult_right(bp0, right)
            return bp0
        def _or_gate(num, bp0, bp1):
            left = matrix([[0, 1, 1], [1, -1, 0]])
            right = matrix([[0, 1], [1, 0]])
            return _two_input_gate(bp0, bp1, left, right)
        def _not_gate(num, bp0):
            right = matrix([[1, 1], [0, -1]])
            mult_right(bp0, right)
            return bp0
        def _xor_gate(num, bp0, bp1):
            left = matrix([[0, 1, 1], [1, -2, 0]])
            right = matrix([[0, 1], [1, 0]])
            return _two_input_gate(bp0, bp1, left, right)
        with open(fname) as f:
            wires = set()
            bp = []
            for lineno, line in enumerate(f, 1):
                if line.startswith('#'):
                    continue
                if line.startswith(':'):
                    continue
                num, rest = line.split(None, 1)
                try:
                    num = int(num)
                except ValueError:
                    raise ParseException(
                        'Line %d: gate index not a number' % lineno)
                gates = {
                    'AND': lambda num, in1, in2: _and_gate(num, bp[in1], bp[in2]),
                    'ID': lambda num, in1: _id_gate(num, bp[in1]),
                    'OR': lambda num, in1, in2: _or_gate(num, bp[in1], bp[in2]),
                    'NOT': lambda num, in1: _not_gate(num, bp[in1]),
                    'XOR': lambda num, in1, in2: _xor_gate(num, bp[in1], bp[in2]),
                }
                if rest.startswith('input'):
                    bp.append(_new_gate(num))
                elif rest.startswith('gate') or rest.startswith('output'):
                    if rest.startswith('output'):
                        output = True
                    _, gate, rest = rest.split(None, 2)
                    inputs = [int(i) for i in rest.split()]
                    if wires.intersection(inputs):
                        raise ParseException(
                            'Line %d: only Boolean formulas supported' % lineno)
                    wires.update(inputs)
                    try:
                        bp.append(gates[gate](num, *inputs))
                    except KeyError:
                        raise ParseException(
                            'Line %d: unsupported gate %s' % (lineno, gate))
                    except TypeError:
                        raise ParseException(
                            'Line %d: incorrect number of arguments given' % lineno)
        return bp[-1]

    def evaluate(self, x):
        assert self.bp
        m = self.bp[0]
        comp = m.zero if x[m.inp] == '0' else m.one
        for m in self.bp[1:]:
            comp *= m.zero if x[m.inp] == '0' else m.one
        return comp[0, comp.ncols() - 1] != 0
