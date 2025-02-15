# Copyright (c) Microsoft. All rights reserved.

# Licensed under the MIT license. See LICENSE.md file in the project root
# for full license information.
# ==============================================================================

"""
Unit tests for reshaping operations.
"""

import numpy as np
import pytest
import cntk as C
from .ops_test_utils import cntk_device
from cntk.axis import Axis
from .. import constant

def test_times_2d_sparse_operand(device_id):
    from .. import times

    dev = cntk_device(device_id)

    vocab_size = 6
    sample_shape = (2, vocab_size)
    input_sparse_indices = [[1, 3], [2, 4], [0, 2]]
    input_data = C.Value.one_hot(input_sparse_indices, sample_shape, device=dev)

    a = C.sequence.input(shape=sample_shape, is_sparse=True, needs_gradient=True, name='a')
    w_init = np.eye(vocab_size, dtype=np.float32)
    w = C.parameter(init=w_init, device=dev)
    a_dense = times(a, w)

    # TODO: Also test the results from grad
    grad = a_dense.grad({a : input_data}, [w, a], as_numpy=False, device=dev)

    res = a_dense.eval({a : input_data}, device=dev)
    assert np.array_equal(res, [[w_init[input_sparse_indices[0]]], [w_init[input_sparse_indices[1]]], [w_init[input_sparse_indices[2]]]])

    a_no_sequence = C.input(shape=sample_shape, is_sparse=True, name='a')
    a_no_sequence_dense = times(a_no_sequence, w)
    res = a_no_sequence_dense.eval({a_no_sequence : input_data}, device=dev)
    assert np.array_equal(res, [w_init[input_sparse_indices[0]], w_init[input_sparse_indices[1]], w_init[input_sparse_indices[2]]])


def test_times_2d_sparse_sequence_operand(device_id):
    from .. import times

    dev = cntk_device(device_id)

    vocab_size = 6
    sample_shape = (2, vocab_size)
    input_sparse_indices = [[1, 3, 4, 2, 0, 5], [2, 4], [0, 2]]
    input_data = C.Value.one_hot(input_sparse_indices, sample_shape, device=dev)

    a = C.sequence.input(shape=sample_shape, is_sparse=True, needs_gradient=True, name='a')
    w_init = np.eye(vocab_size, dtype=np.float32)
    w = C.parameter(init=w_init, device=dev)
    a_dense = times(a, w)

    # TODO: Also test the results from grad
    grad = a_dense.grad({a : input_data}, [w, a], as_numpy=False, device=dev)

    res = a_dense.eval({a : input_data}, device=dev)
    expected = [w_init[input_sparse_indices[0]], w_init[input_sparse_indices[1]], w_init[input_sparse_indices[2]]]
    assert np.array_equal(res[0], [expected[0][0:2], expected[0][2:4], expected[0][4:6]])
    assert np.array_equal(res[1], [expected[1]])
    assert np.array_equal(res[2], [expected[2]])


def test_training_2d_sparse_sequence_operand(device_id):
    from .. import times
    from cntk.losses import cross_entropy_with_softmax

    dev = cntk_device(device_id)
    vocab_size = 6
    additional_axis_dim = 2
    out_dim = 4
    w_init = np.float32(np.random.rand(vocab_size, out_dim))
    input_shape = (additional_axis_dim, vocab_size)
    label_shape = (additional_axis_dim, out_dim)

    def create_trainer(use_sparse, device):
        a = C.sequence.input(shape=input_shape, is_sparse=use_sparse, name='input')
        w = C.parameter(init=w_init, device=dev)
        z = times(a, w)
    
        l = C.sequence.input(shape=label_shape, is_sparse=use_sparse, name='label')
        loss = cross_entropy_with_softmax(z, l, axis=-1)
        trainer = C.Trainer(z, (loss, None), C.sgd(z.parameters, lr=C.learning_rate_schedule(0.7, C.UnitType.sample)))
        return (a, l, w, trainer)

    # Run with sparse inputs
    input_sparse_indices = [[1, 3, 4, 2, 0, 5], [2, 4], [0, 2]]
    input_data = C.Value.one_hot(input_sparse_indices, input_shape, device=dev)
    label_sparse_indices = [[1, 3, 0, 2, 1, 0], [2, 1], [1, 3]]
    label_data = C.Value.one_hot(label_sparse_indices, label_shape, device=dev)

    input_var, label_var, weights, trainer = create_trainer(use_sparse=True, device=dev)
    trainer.train_minibatch({input_var:input_data, label_var:label_data}, device=dev)
    weights_with_sparse_input = weights.value

    # Run with dense inputs
    i1 = np.eye(vocab_size, dtype=np.float32)
    dense_input = [i1[input_sparse_indices[0]], i1[input_sparse_indices[1]], i1[input_sparse_indices[2]]]
    i2 = np.eye(out_dim, dtype=np.float32)
    dense_label = [i2[label_sparse_indices[0]], i2[label_sparse_indices[1]], i2[label_sparse_indices[2]]]
    
    dense_input_data = [np.reshape(dense_input[0], (-1,) + input_shape), dense_input[1], dense_input[2]]
    dense_label_data = [np.reshape(dense_label[0], (-1,) + label_shape), dense_label[1], dense_label[2]]

    input_var, label_var, weights, trainer = create_trainer(use_sparse=False, device=dev)
    trainer.train_minibatch({input_var:dense_input_data, label_var:dense_label_data}, device=dev)
    weights_with_dense_input = weights.value

    assert np.allclose(weights_with_sparse_input, weights_with_dense_input)


def test_training_3d_sparse_sequence_with_recurrence(device_id):
    from .. import times, times_transpose, reshape
    from cntk.losses import cross_entropy_with_softmax

    dev = cntk_device(device_id)
    vocab_size = 3
    additional_axis_dim1 = 2
    additional_axis_dim2 = 3
    out_dim = 2
    w_init_i = np.float32(np.random.rand(vocab_size, out_dim))
    w_init_h = np.float32(np.random.rand(out_dim, out_dim))
    input_shape = (additional_axis_dim1, additional_axis_dim2, vocab_size)
    label_shape = (additional_axis_dim1 * additional_axis_dim2, out_dim)

    def create_trainer(use_sparse, device):
        a = C.sequence.input(shape=input_shape, is_sparse=use_sparse, name='input')
        w_i = C.parameter(init=w_init_i, device=dev)
        a_projection = times(a, w_i)

        p_o = C.placeholder()
        h = C.past_value(p_o)
        w_h = C.parameter(init=w_init_h, device=dev)
        h_projection = times(h, w_h)        
        z = a_projection + h_projection
        z = z.replace_placeholder(z)
        z = reshape(z, label_shape)

        l = C.sequence.input(shape=label_shape, is_sparse=use_sparse, name='label')
        loss = cross_entropy_with_softmax(z, l, axis=-1)
        trainer = C.Trainer(z, (loss, None), C.sgd(z.parameters, lr=C.learning_rate_schedule(0.7, C.UnitType.sample)))
        return (a, l, w_i, w_h, trainer)

    # Run with sparse inputs
    input_sparse_indices = [[1, 0, 1, 2, 0, 1, 0, 2, 1, 1, 0, 2], [2, 0, 1, 1, 2, 0]]
    input_data = C.Value.one_hot(input_sparse_indices, input_shape, device=dev)
    label_sparse_indices = [[1, 0, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0], [1, 1, 0, 0, 0, 1]]
    label_data = C.Value.one_hot(label_sparse_indices, label_shape, device=dev)

    input_var, label_var, weights_i, weights_h, trainer = create_trainer(use_sparse=True, device=dev)
    trainer.train_minibatch({input_var:input_data, label_var:label_data}, device=dev)
    weights_with_sparse_input_i = weights_i.value
    weights_with_sparse_input_h = weights_h.value

    # Run with dense inputs
    i1 = np.eye(vocab_size, dtype=np.float32)
    dense_input = [i1[input_sparse_indices[0]], i1[input_sparse_indices[1]]]
    i2 = np.eye(out_dim, dtype=np.float32)
    dense_label = [i2[label_sparse_indices[0]], i2[label_sparse_indices[1]]]

    dense_input_data = [np.reshape(dense_input[0], (-1,) + input_shape), np.reshape(dense_input[1], (-1,) + input_shape)]
    dense_label_data = [np.reshape(dense_label[0], (-1,) + label_shape), np.reshape(dense_label[1], (-1,) + label_shape)]

    input_var, label_var, weights_i, weights_h, trainer = create_trainer(use_sparse=False, device=dev)
    trainer.train_minibatch({input_var:dense_input_data, label_var:dense_label_data}, device=dev)
    weights_with_dense_input_i = weights_i.value
    weights_with_dense_input_h = weights_h.value

    assert np.allclose(weights_with_sparse_input_i, weights_with_dense_input_i)
    assert np.allclose(weights_with_sparse_input_h, weights_with_dense_input_h)


def test_times_sparse_operand_reduce_multiple_axes():
    from .. import times

    vocab_size = 3
    additional_axis_dim1 = 2
    additional_axis_dim2 = 3
    out_dim = 2
    w_init = np.float32(np.random.rand(vocab_size, additional_axis_dim2, out_dim))
    input_shape = (additional_axis_dim1, additional_axis_dim2, vocab_size)

    a = C.input(shape=input_shape, is_sparse=True, name='input')
    w = C.parameter(init=w_init)
    
    with pytest.raises(RuntimeError):
        a_projection = times(a, w)
   