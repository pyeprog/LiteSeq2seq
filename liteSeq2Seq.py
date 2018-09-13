'''
MIT License

Copyright (c) 2018 Weilong Liao

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
import _pickle as pkl
import os
import re
import math
from collections import Counter
from collections import namedtuple
from random import random
from multiprocessing import Pool
from multiprocessing import Process
from itertools import chain

# GatherTree ops don't load automatically. Adding import to force library to load
# Fixed the KeyError: GatherTree
from tensorflow.contrib.seq2seq.python.ops import beam_search_ops

# Suppress warning log
tf.logging.set_verbosity(tf.logging.FATAL)

DEBUG = 1
if DEBUG:
    from pprint import pprint

Hyparams = namedtuple('Hyparams', [
    'embedding_dim',
    'rnn_layer_size',
    'n_rnn_layers',
    'beam_width',
    'keep_prob',
    'valid_portion',
    'train_batch_size',
    'infer_batch_size',
    'max_gradient_norm',
    'epoch',
    'max_global_step',
    'learning_rate',
    'decay_rate',
    'decay_every',
    'decay_start_at',
    'n_buckets',
    'vocab_remain_rate',
    'input_seq_min_len',
    'input_seq_max_len',
    'bleu_max_order',
    'bleu_smooth',
    'report_every',
    'show_every',
    'summary_every',
    'save_every',
    ])

class Seq2seq:
    model_path = './models'

    # Default hyper parameters
    # Class variable
    hyparams = Hyparams(
        embedding_dim=512,
        rnn_layer_size=1024, #even number only
        n_rnn_layers=3,
        beam_width=3,
        keep_prob=0.8,
        valid_portion=0.05,
        train_batch_size=32,
        infer_batch_size=1,
        max_gradient_norm=5.0,
        epoch=10,
        max_global_step=float('inf'),
        learning_rate=1e-3,
        decay_rate=0.5,
        decay_every=1e3,
        decay_start_at=8e3,
        n_buckets=50,
        vocab_remain_rate=0.97,
        input_seq_min_len=1,
        input_seq_max_len=float('inf'),
        bleu_max_order=4,
        bleu_smooth=False,
        report_every=50,
        show_every=200,
        summary_every=50,
        save_every=500
        )


    @classmethod
    def set_model_dir(cls, model_path):
        '''
        Set the dir to save models
        @model_path: str, directory to save your models, default to ./models
        @return: None
        '''
        cls.model_path = model_path
        if not os.path.isdir(model_path):
            os.mkdir(model_path)

    def __init__(self,
            embedding_dim=None,
            rnn_layer_size=None,
            n_rnn_layers=None,
            beam_width=None,
            keep_prob=None,
            valid_portion=None,
            train_batch_size=None,
            infer_batch_size=None,
            max_gradient_norm=None,
            epoch=None,
            max_global_step=None,
            learning_rate=None,
            decay_rate=None,
            decay_every=None,
            decay_start_at=None,
            n_buckets=None,
            vocab_remain_rate=None,
            input_seq_min_len=None,
            input_seq_max_len=None,
            bleu_max_order=None,
            bleu_smooth=None,
            report_every=None,
            show_every=None,
            summary_every=None,
            save_every=None,
            ):
        '''
        Create a seq2seq instance
        @embedding_dim  :int, Embedding layer size
        @rnn_layer_size :int, Single lstm layer size, EVEN NUMBER ONLY, set for both encoder and decoder
        @n_rnn_layers :int, Number of layers of lstm network, set for both encoder and decoder
        @beam_width :int, Width of beam search
        @keep_prob :float, Keep probability for each rnn node
        @valid_portion :float, Portion seperated for validtion
        @train_batch_size :int, Batch size while training
        @infer_batch_size :int, Batch size while infering
        @max_gradient_norm :float, Clip value for global gradients
        @epoch :int, Number of training epoch
        @max_global_step :int, Maximum training steps, default to infinity, which means training for {epoch} times
        @learning_rate :float, The learning rate
        @decay_rate :float, The decay rate of learning rate
        @decay_every :int, For every {this} steps, learning_rate=learning_rate * decay_rate
        @decay_start_at :int, The learning rate begin to decay after training {this} number of steps
        @n_buckets :int, Seperate training sequence into {this} buckets, training sequences in same bucket have similar length
        @vocab_remain_rate :float, Choose a vocab size that can cover {this} percentage of total words
        @input_seq_min_len: int, Minimum length of sequence that used for training
        @input_seq_max_len: int, Maximum length of sequence that used for training
        @bleu_max_order :int, the max order for n-gram
        @bleu_smooth :bool, whether use smoothed bleu score. If False, 0.0 would be more frequent in bleu score.
        @report_every :int, Print validation score for every {this} steps
        @show_every :int, Print example of transformation for every {this} steps
        @summary_every :int, Save summery info for tensorboard for every {this} steps
        @save_every :int, Save checkpoint for every {this} steps
        @return: None
        '''
                
        self.init_hyparams = Hyparams(
            embedding_dim,
            rnn_layer_size,
            n_rnn_layers,
            beam_width,
            keep_prob,
            valid_portion,
            train_batch_size,
            infer_batch_size,
            max_gradient_norm,
            epoch,
            max_global_step,
            learning_rate,
            decay_rate,
            decay_every,
            decay_start_at,
            n_buckets,
            vocab_remain_rate,
            input_seq_min_len,
            input_seq_max_len,
            bleu_max_order,
            bleu_smooth,
            report_every,
            show_every,
            summary_every,
            save_every,
        )

        # Specify save path of models
        if not os.path.isdir(self.model_path):
            os.mkdir(self.model_path)

        # Specify unique id for each instance
        self._id = (str(random())[2:] + str(random())[2:])[:20]
        self.model_ckpt_dir = os.path.join(self.model_path, self._id)
        self.model_ckpt_path = os.path.join(self.model_ckpt_dir, 'checkpoint.ckpt')
        
        self.tp = TextProcessor()
        
        self.hyparams = self._merge(self.hyparams, self.init_hyparams)


    def _merge(self, base_hyp, new_hyp):
        '''
        Merge two namedtuple into one. 
        E.g. base_hyp.x = 4 and new_hyp.x = 2, after merging, return hyp.x = 2
        However, if base_hyp.x = 4 and new_hyp.x = None, after merging, return hyp.x = 4
        @base_hyp: namedtuple, basic hyperparameters
        @new_hyp: namedtyple, updating hyperparameters 
        '''
        return Hyparams(*[n_v or o_v for o_v, n_v in zip(base_hyp, new_hyp)])
            

    def set_id(self, new_id):
        '''
        Set new id to this seq2seq instance, it will modify the saved model path also.
        @new_id: str, new id specified
        @return: None
        '''
        last_model_ckpt_dir = self.model_ckpt_dir
        if os.path.isdir(os.path.join(self.model_path, new_id)):
            raise RuntimeError('model named {} is existed'.format(new_id))

        self._id = str(new_id)
        self.model_ckpt_dir = os.path.join(self.model_path, self._id)
        self.model_ckpt_path = os.path.join(self.model_ckpt_dir, 'checkpoint.ckpt')
        if os.path.isdir(last_model_ckpt_dir):
            os.rename(last_model_ckpt_dir, self.model_ckpt_dir)


    def __delete__(self):
        '''
        Close session and free occupied memory
        '''
        if hasattr(self, 'sess'):
            self.sess.close()


    def get_id(self):
        '''
        Return id of this seq2seq instance
        '''
        return self._id


    def get_ckpt_dir(self):
        '''
        Return the saving path of this seq2seq instance
        '''
        return self.model_ckpt_dir


    def _get_ngrams(self, segment, max_order):
        '''
        Calculate the ngrams for bleu score
        @segment: list, list of words for one sentence
        @max_order: int, 1-gram, 2-gram ... max_order-gram will be calculated
        @return: dict, key: tuple of words, value: number of occurrence of the word tuple.
        '''
        ngram_counts = Counter()
        for order in range(1, max_order + 1):
            for i in range(0, len(segment) - order + 1):
                ngram = tuple(segment[i:i+order])
                ngram_counts[ngram] += 1
        return ngram_counts


    def _bleu(self, gen_lists, refer_lists, max_order=4, smooth=True):
        '''
        Calculate the bleu score given a list of generated sentence and a list of given sentence for reference.
        @gen_lists: list, each item in list is a list of word token. [[token0, token1, ..], [tokenX, tokenY, ..], ..]
        @refer_lists: list, each item in list is a list of reference word token, like gen_lists
        @max_order: int, the max order for n-gram
        @smooth: bool, if False, bleu score might be 0.0 more often.
        @return: float, the bleu score of the gen_lists
        '''
        matches_by_order = [0] * max_order
        possible_matches_by_order = [0] * max_order
        refer_length = 0
        gen_length = 0

        # In my case, generated string only has 1 reference string
        for (refer_list, gen_list) in zip(refer_lists, gen_lists):
            refer_length += len(refer_list)
            gen_length += len(gen_list)

            refer_ngram_counts = self._get_ngrams(refer_list, max_order)
            gen_ngram_counts = self._get_ngrams(gen_list, max_order)
            overlap = gen_ngram_counts & refer_ngram_counts

            for ngram in overlap:
                matches_by_order[len(ngram)-1] += overlap[ngram]

            for order in range(1, max_order+1):
                possible_matches = len(gen_list) - order + 1
                if possible_matches > 0:
                    possible_matches_by_order[order-1] += possible_matches

        precisions = [0] * max_order
        for i in range(0, max_order):
            if smooth:
                precisions[i] = ((matches_by_order[i] + 1.) /
                               (possible_matches_by_order[i] + 1.))
            else:
                if possible_matches_by_order[i] > 0:
                    precisions[i] = (float(matches_by_order[i]) /
                                 possible_matches_by_order[i])
                else:
                    precisions[i] = 0.0

        if min(precisions) > 0:
            # Tensorflow nmt group use this
            ## p_log_sum = sum((1. / max_order) * np.log(p) for p in precisions)
            p_log_sum = sum((1. / max_order) * p for p in precisions)
            geo_mean = np.exp(p_log_sum)
        else:
            geo_mean = 0.0

        ratio = float(gen_length) / refer_length

        if ratio > 1.0:
            bp = 1.
        else:
            bp = np.exp(1 - 1. / ratio)

        bleu = geo_mean * bp

        return bleu


    def _rnn_cell(self, rnn_size, keep_prob):
        '''
        Generate lstm cell with dropout wrapper
        @rnn_size: int, the size of single layer
        @keep_prob: float, the keep probability for each rnn node
        @return: rnn_cell with dropout wrapper
        '''
        lstm_cell = tf.nn.rnn_cell.LSTMCell(rnn_size)
                #initializer=tf.random_uniform_initializer(-0.1, 0.1))
        return tf.contrib.rnn.DropoutWrapper(lstm_cell, input_keep_prob=keep_prob, output_keep_prob=1.0)

    def _padding_batch(self, inputs, targets, batch_size, input_padding_val=0, target_padding_val=0, forever=False):
        '''
        Generate padding batch
        @inputs: list, each item of the list is a list of word tokens for encoding
        @targets: list, each item of the list is a list of word tokens for decoding
        @batch_size: int, the batch size
        @input_padding_val: int, the token number of padding for encoding sequences
        @target_padding_val: int, the token number of padding for decoding sequences 
        @forever: bool, if True, repeating generating batch forever. if False, then just one round
        @return: generator, for each iteration it will return, batch_encoding_seqs, batch_encoding_seqs_lens, batch_decoding_seqs, batch_decoding_seqs_lens
        '''
        decoder_eos_id = self.decoder_vocab_to_int['<EOS>']
        while True:
            for i in range(0, len(targets) // batch_size):
                start_i = i * batch_size

                batch_inputs = inputs[start_i: start_i+batch_size]
                batch_targets = [line+[decoder_eos_id] for line in targets[start_i: start_i+batch_size]]

                batch_inputs_lens = [len(line) for line in batch_inputs]
                batch_targets_lens = [len(line) for line in batch_targets]

                inputs_cur_maxLen = np.max(batch_inputs_lens)
                targets_cur_maxLen = np.max(batch_targets_lens)

                padding_batch_inputs = np.array([line + [input_padding_val]*(inputs_cur_maxLen-len(line)) for line in batch_inputs])
                padding_batch_targets = np.array([line + [target_padding_val]*(targets_cur_maxLen-len(line)) for line in batch_targets])

                yield padding_batch_inputs, [inputs_cur_maxLen]*batch_size, padding_batch_targets, [targets_cur_maxLen]*batch_size
            
            if not forever:
                break

    
    def _parse_dict(self, file_path):
        '''
        Given text file, return the vocab_to_int and int_to_vocab dictionary. The vocab size is effected by 'vocab_remain_rate' 
        @file_path: str, the file path of text dataset
        @return: (dict, dict), return a tuple of (int_to_vocab, vocab_to_int)
        '''
        with open(file_path, 'r') as fp:
            lines = fp.readlines()

        word_count = Counter()
        vocabs = ['<PAD>', '<UNK>', '<GO>', '<EOS>']
        n_lines = len(lines)
        n_words = 0

        for i, line in enumerate(lines):
            if i % 100 == 0 or i + 1 == n_lines:
                print('\rParsing dictionary {}/{}'.format(i+1, n_lines), end='', flush=True)
            
            for word in line.lower().split():
                word_count[word] += 1
                n_words += 1

        print('\tFinished')

        cur_count = 0
        for i, (word, count) in enumerate(word_count.most_common()):
            cur_count += count
            if cur_count / n_words <= self.hyparams.vocab_remain_rate:
                vocabs.append(word)
            else: break
            print('\rFilter vocabs {}/{} = {}'.format(i+1, n_words, cur_count/n_words), end='', flush=True)

        int_to_vocab = {i:word for i, word in enumerate(vocabs)}
        vocab_to_int = {word:i for i, word in enumerate(vocabs)}
        print('\tFinished')
        print('Total len of vocabs: {}'.format(len(vocabs)))
        return int_to_vocab, vocab_to_int


    def _parse_seq(self, encode_file_path, decode_file_path, encoder_vocab_to_int, decoder_vocab_to_int, n_buckets=0):
        '''
        Parse both files for encoding and decoding, given number of buckets and their vocab_to_int dictionary.
        @encode_file_path: str, the file path for encoding
        @decode_file_path: str, the file path for decoding
        @encodr_vocab_to_int: dict, the vocab_to_int dictionary for encoding
        @decodr_vocab_to_int: dict, the vocab_to_int dictionary for decoding
        @n_buckets: int, the number of bucket for rearranging order of sequences, that lengths of sequences in the same bucket is as close as possible.
        @return: (list, list), return a tuple of two lists, (encode_seqs, decode_seqs), each of them is a list of tokenized words list.
        '''
        with open(encode_file_path, 'r') as fp:
            encode_lines = fp.readlines()
        with open(decode_file_path, 'r') as fp:
            decode_lines = fp.readlines()

        assert len(encode_lines) == len(decode_lines), 'encode file and decode file should have same number of lines'

        encode_unk_id = encoder_vocab_to_int['<UNK>']
        decode_unk_id = decoder_vocab_to_int['<UNK>']

        n_lines = len(encode_lines)

        parsed_encode_lines = []
        parsed_decode_lines = []

        for i, (encode_line, decode_line) in enumerate(zip(encode_lines, decode_lines)):
            if i % 100 == 0 or i + 1 == n_lines:
                print('\rParsing sequence {}/{}'.format(i+1, n_lines), end='', flush=True)

            encode_line_split = encode_line.lower().split()
            if not (self.hyparams.input_seq_min_len <= len(encode_line_split) <= self.hyparams.input_seq_max_len):
                continue
            cur_encode_line = []
            cur_encode_n_unk = 0
            for word in encode_line_split:
                if word not in encoder_vocab_to_int:
                    cur_encode_n_unk += 1
                cur_encode_line.append(encoder_vocab_to_int.get(word, encode_unk_id))

            decode_line_split = decode_line.lower().split()
            if not (self.hyparams.input_seq_min_len <= len(decode_line_split) <= self.hyparams.input_seq_max_len):
                continue
            cur_decode_line = []
            cur_decode_n_unk = 0
            for word in decode_line_split:
                if word not in decoder_vocab_to_int:
                    cur_decode_n_unk += 1
                cur_decode_line.append(decoder_vocab_to_int.get(word, decode_unk_id))

            if len(cur_encode_line) > 0 and len(cur_decode_line) > 0 and \
                    cur_encode_n_unk / len(cur_encode_line) < 0.2 and cur_decode_n_unk / len(cur_decode_line) < 0.2:
                parsed_encode_lines.append(cur_encode_line)
                parsed_decode_lines.append(cur_decode_line)


        if n_buckets > 1:
            print('\tBucketizing...', end='')
            encode_line_lens = [*map(len, parsed_encode_lines)]
            decode_line_lens = [*map(len, parsed_decode_lines)]

            max_encode_len = max(encode_line_lens)
            max_decode_len = max(decode_line_lens)

            lens_tuple = [(max(enc_len, dec_len), i) for i, (enc_len, dec_len) in enumerate(zip(encode_line_lens, decode_line_lens))] 
            bucket_width = (max_encode_len + n_buckets - 1) // n_buckets 
            buckets = {}
            for i, (enc_len, dec_len) in enumerate(zip(encode_line_lens, decode_line_lens)):
                b_id = max(enc_len, dec_len) // bucket_width
                buckets[b_id] = buckets.get(b_id, set())
                buckets[b_id].add(i)

            decode_idxs = []
            for b_id in sorted(buckets.keys()):
                decode_idxs.extend(list(buckets[b_id]))

            parsed_encode_lines = [parsed_encode_lines[decode_idxs[i]] for i in range(len(decode_idxs))]
            parsed_decode_lines = [parsed_decode_lines[decode_idxs[i]] for i in range(len(decode_idxs))]

        print('\tFinished')

        return parsed_encode_lines, parsed_decode_lines

    def lr_schedule(self, lr, start_p, every_step, decay_rate):
        '''
        A learning rate scheduler for flexible learning rate decaying
        @lr: float, the original learning rate
        @start_p: int, when global step reach start_p, the learning rate begins to decay
        @every_step: int, the learning rate will decay for every {this} steps
        @decay_rate: float, new learning rate = last learning rate * decay_rate
        @return: generator, each iteration will return a learning rate
        '''
        global_step = 0
        while True:
            if global_step > start_p:
                start_p += every_step
                lr *= decay_rate
            global_step += 1
            yield lr

    @staticmethod
    def _unwrap_self_train(*arg, **kwarg):
        '''
         Process wrapper, since multiprocessing cannot call instance method
         You need a outer function to wrap you instance method
        '''
        return Seq2seq._train(*arg, **kwarg)

    
    def train(self, encode_file_path, decode_file_path, load_model_path=None):
        '''
        A process wrapper for _train method
        If you use gpu to train the model, memory will not be released, even after session closed. :(
        However, if the process is killed, memory will be released.
        Thus for training, we spawn a process to do the training work.
        '''
        with Pool(1) as process:
            params = (self, encode_file_path, decode_file_path, load_model_path)
            process.apply(self._unwrap_self_train, [*params])


    def _train(self, encode_file_path, decode_file_path, load_model_path=None):
        '''
        Main training method. After training your model instance will be saved.
        @encode_file_path: str, the path of the encoder training file
        @decode_file_path: str, the path of the decoder training file
        @load_model_path: str, the path of existed model directory
        @return: None
        '''
        if not load_model_path:
            # Train model from start
            print('Train new model')
            
            # Create dictionary
            self.encoder_int_to_vocab, self.encoder_vocab_to_int = self._parse_dict(encode_file_path)
            self.decoder_int_to_vocab, self.decoder_vocab_to_int = self._parse_dict(decode_file_path)

            # Create seqs
            self.encode_seqs, self.decode_seqs = self._parse_seq(encode_file_path, decode_file_path, self.encoder_vocab_to_int, self.decoder_vocab_to_int, n_buckets=self.hyparams.n_buckets)

            # create placeholder
            ## why the shape is [None, None]? explain
            self.graph = tf.Graph()
            with self.graph.as_default():
                encoder_input = tf.placeholder(tf.int32, shape=[None, None], name='inputs')
                decoder_target = tf.placeholder(tf.int32, shape=[None, None], name='targets')
                decoder_input = tf.concat(
                        [tf.fill([self.hyparams.train_batch_size,1], self.decoder_vocab_to_int['<GO>']), 
                        tf.strided_slice(decoder_target, [0,0], [self.hyparams.train_batch_size,-1], [1,1])],
                        1)
                keep_prob = tf.placeholder(tf.float32, name='dropout')
                
                ## why does it need sequence length placeholder? explain
                encoder_input_seq_lengths = tf.placeholder(tf.int32, shape=[None,], name='source_lens')
                decoder_target_seq_lengths = tf.placeholder(tf.int32, shape=[None,], name='target_lens')



                ###### ENCODER ######
                with tf.variable_scope('encoder'):
                    encoder_wordvec = tf.contrib.layers.embed_sequence(encoder_input, len(self.encoder_int_to_vocab), self.hyparams.embedding_dim,
                            initializer=tf.initializers.random_uniform(-0.1,0.1))
                    
                    # reshape_encoder_input = tf.reshape(encoder_input, [])
                    # encoder_embedding_weights = tf.Variable(tf.random_uniform([len(self.encoder_int_to_vocab), self.hyparams.embedding_dim], minval=-0.1, maxval=0.1), name='encoder_embed_weight')
                    # encoder_embedding_bias = tf.Variable(tf.random_uniform([self.hyparams.embedding_dim], minval=-0.1, maxval=0.1), name='encoder_embed_bias')
                    # encoder_wordvec = tf.nn.embedding_lookup(encoder_embedding_weights, encoder_input) #+ encoder_embedding_bias

                    # # To use stacked uni-directional rnn encoder, open this
                    # rnn_cell_list = [self._rnn_cell(self.hyparams.rnn_layer_size, keep_prob) for _ in range(self.hyparams.n_rnn_layers)]
                    # encoder_rnn = tf.nn.rnn_cell.MultiRNNCell(rnn_cell_list)
                    # encoder_output, encoder_final_state = tf.nn.dynamic_rnn(encoder_rnn, encoder_wordvec, sequence_length=encoder_input_seq_lengths, dtype=tf.float32)

                    # # print(encoder_output.get_shape())
                    # # print(encoder_final_state)


                    # To use stacked bi-directional rnn encoder, open this
                    # Explain for the state concat, explain
                    rnn_cell_list_forward = [self._rnn_cell(self.hyparams.rnn_layer_size // 2, keep_prob) for _ in range(self.hyparams.n_rnn_layers)]
                    rnn_cell_list_backward = [self._rnn_cell(self.hyparams.rnn_layer_size // 2, keep_prob) for _ in range(self.hyparams.n_rnn_layers)]

                    encoder_output, forward_final_state, backward_final_state = tf.contrib.rnn.stack_bidirectional_dynamic_rnn(
                            rnn_cell_list_forward, rnn_cell_list_backward, encoder_wordvec,
                            sequence_length=encoder_input_seq_lengths, time_major=False,
                            dtype=tf.float32
                            )
                    

                    # maybe the encoder_final_state can be updated
                    # Use tensorboard to check it
                    encoder_final_state = []
                    for forward_cell_state, backward_cell_state in zip(forward_final_state, backward_final_state):
                        concated_state = tf.concat([forward_cell_state.c, backward_cell_state.c], -1)
                        concated_output = tf.concat([forward_cell_state.h, backward_cell_state.h], -1)
                        encoder_final_state.append(tf.nn.rnn_cell.LSTMStateTuple(concated_state, concated_output))
                    encoder_final_state = tuple(encoder_final_state)

                    if DEBUG:
                        tf.summary.histogram('encoder_output', encoder_output)
                        tf.summary.histogram('encoder_forward_state', forward_final_state)
                        tf.summary.histogram('encoder_backward_state', backward_final_state)




                ##### DECODER ######

                with tf.variable_scope('decoder_cell'):
                    decoder_embedding_weights = tf.Variable(tf.random_uniform([len(self.decoder_int_to_vocab), self.hyparams.embedding_dim], minval=-0.1, maxval=0.1), name='decoder_embed_weight')
                    # decoder_embedding_bias = tf.Variable(tf.random_uniform([self.hyparams.embedding_dim], minval=-0.1, maxval=0.1), name='decoder_embed_bias')
                    decoder_wordvec = tf.nn.embedding_lookup(decoder_embedding_weights, decoder_input) #+ decoder_embedding_bias
                    rnn_cell_list = [self._rnn_cell(self.hyparams.rnn_layer_size, keep_prob) for _ in range(self.hyparams.n_rnn_layers)]
                    decoder_rnn = tf.nn.rnn_cell.MultiRNNCell(rnn_cell_list)
                    decoder_output_dense_layer = tf.layers.Dense(len(self.decoder_int_to_vocab), use_bias=False,
                            kernel_initializer=tf.truncated_normal_initializer(mean=0.0, stddev=0.1), name='decoder_output_embedding')

                with tf.variable_scope('decoder'):
                    training_helper = tf.contrib.seq2seq.TrainingHelper(
                            inputs=decoder_wordvec,
                            sequence_length=decoder_target_seq_lengths,
                            time_major=False)

                    # Add attention mechanism
                    attention_mechanism = tf.contrib.seq2seq.LuongAttention(
                            self.hyparams.rnn_layer_size, encoder_output,
                            memory_sequence_length=encoder_input_seq_lengths
                            )

                    # Wrapper Attention mechanism on plain rnn cell first
                    training_decoder = tf.contrib.seq2seq.AttentionWrapper(
                            decoder_rnn, attention_mechanism,
                            attention_layer_size=self.hyparams.rnn_layer_size
                            )

                    # Make decoder and it's initial state with wrapped rnn cell
                    training_decoder = tf.contrib.seq2seq.BasicDecoder(
                            training_decoder,
                            # decoder_rnn, # Used for vanilla case
                            training_helper,
                            training_decoder.zero_state(self.hyparams.train_batch_size,tf.float32).clone(cell_state=encoder_final_state),
                            # encoder_final_state, # Used for vanilla case
                            decoder_output_dense_layer
                            )

                    training_decoder_output = tf.contrib.seq2seq.dynamic_decode(
                            training_decoder,
                            impute_finished=True,
                            maximum_iterations=tf.reduce_max(decoder_target_seq_lengths)
                            )[0]

                with tf.variable_scope('decoder', reuse=True):
                    # Tiled start_token <GO>
                    start_tokens = tf.tile(
                            tf.constant([self.decoder_vocab_to_int['<GO>']], dtype=tf.int32),
                            [self.hyparams.infer_batch_size],
                            name='start_tokens')

                    # # To use greedy decoder, open this
                    # inference_helper = tf.contrib.seq2seq.GreedyEmbeddingHelper(
                     #     decoder_embedding_weights,
                     #     start_tokens,
                     #     self.decoder_vocab_to_int['<EOS>']
                     #     )

                    # inference_decoder = tf.contrib.seq2seq.BasicDecoder(
                     #     inference_decoder,
                     #     # decoder_rnn, # Used for vanilla case
                     #     inference_helper,
                     #     inference_decoder.zero_state(self.hyparams.train_batch_size,tf.float32).clone(cell_state=encoder_final_state),
                     #     # encoder_final_state, # Used for vanilla case
                     #     decoder_output_dense_layer
                     #     )

                    # To use beam search decoder, open this
                    # Beam search tile
                    tiled_encoder_output = tf.contrib.seq2seq.tile_batch(encoder_output, multiplier=self.hyparams.beam_width)
                    tiled_encoder_input_seq_lengths = tf.contrib.seq2seq.tile_batch(encoder_input_seq_lengths, multiplier=self.hyparams.beam_width)
                    # Explain the tile state, need explain, tile_batch can handle nested state
                    tiled_encoder_final_state = tf.contrib.seq2seq.tile_batch(encoder_final_state, multiplier=self.hyparams.beam_width)

                    attention_mechanism = tf.contrib.seq2seq.LuongAttention(
                            self.hyparams.rnn_layer_size, tiled_encoder_output,
                            memory_sequence_length=tiled_encoder_input_seq_lengths
                            )

                    inference_decoder = tf.contrib.seq2seq.AttentionWrapper(
                            decoder_rnn, attention_mechanism,
                            attention_layer_size=self.hyparams.rnn_layer_size
                            )

                    inference_decoder = tf.contrib.seq2seq.BeamSearchDecoder(
                            inference_decoder,
                            decoder_embedding_weights,
                            start_tokens,
                            self.decoder_vocab_to_int['<EOS>'],
                            inference_decoder.zero_state(self.hyparams.infer_batch_size*self.hyparams.beam_width,tf.float32).clone(
                                cell_state=tiled_encoder_final_state
                                ),
                            self.hyparams.beam_width,
                            decoder_output_dense_layer,
                            length_penalty_weight=0.0
                            )

                    inference_decoder_output = tf.contrib.seq2seq.dynamic_decode(
                            inference_decoder,
                            impute_finished=False,
                            maximum_iterations=2*tf.reduce_max(encoder_input_seq_lengths)
                            )[0]



                ##### OPTIMIZATION #####
                with tf.variable_scope('optimization'):

                    # Get train_op
                    training_logits = tf.identity(training_decoder_output.rnn_output, name='logits')
                    inference_logits = tf.identity(inference_decoder_output.predicted_ids[:,:,0], name='predictions')
                    # inference_logits = tf.identity(inference_decoder_output.rnn_output, name='predictions')
                    decoder_output = tf.identity(training_decoder_output.sample_id, name='training_output')

                    # Why mask, explain
                    mask = tf.sequence_mask(decoder_target_seq_lengths, tf.reduce_max(decoder_target_seq_lengths), dtype=tf.float32, name='mask')
                    
                    global_step = tf.Variable(0, trainable=False)

                    # Cost
                    cost = tf.contrib.seq2seq.sequence_loss(
                            training_logits,
                            decoder_target,
                            mask,
                            name='cost'
                            )

                    # # Cost alternative
                    # crossent = tf.nn.sparse_softmax_cross_entropy_with_logits(
                    #         labels=decoder_target, logits=training_logits
                    #         )
                    # cost = (tf.reduce_sum(crossent * mask) / self.hyparams.train_batch_size)


                    # lr = tf.train.exponential_decay(self.hyparams.learning_rate, global_step, DECAY_STEP, self.hyparams.decay_rate, True)
                    lr = tf.placeholder(tf.float32, name='learning_rate')
                    # optimizer = tf.train.GradientDescentOptimizer(lr)
                    optimizer = tf.train.AdamOptimizer(lr)
                    gradients = optimizer.compute_gradients(cost)
                    capped_gradients = [(tf.clip_by_value(grad, -self.hyparams.max_gradient_norm, self.hyparams.max_gradient_norm), var) for grad, var in gradients if grad is not None]
                    train_op = optimizer.apply_gradients(capped_gradients, global_step=global_step, name='train_op')

                    # # Clip by global norm
                    # trainable_params = tf.trainable_variables()
                    # gradients = tf.gradients(cost, trainable_params)
                    # capped_gradients,_ = tf.clip_by_global_norm(gradients, self.hyparams.max_gradient_norm)
                    # optimizer = tf.train.AdamOptimizer(self.hyparams.learning_rate)
                    # train_op = optimizer.apply_gradients(zip(capped_gradients, trainable_params), global_step=global_step, name='train_op')

                if DEBUG:
                    tf.summary.scalar('seq_loss', cost)
                    # tf.summary.scalar('learning_rate', optimizer._lr)

                    trainable_params = tf.trainable_variables()
                    gradients = tf.gradients(cost, trainable_params)
                    for param, gradient in zip(trainable_params, gradients):
                        if gradient is not None:
                            tf.summary.histogram(param.name, gradient)


                # Save op to collection for further use
                tf.add_to_collection("optimization", train_op)
                tf.add_to_collection("optimization", cost)
                tf.add_to_collection("optimization", global_step)

                # Initialize the graph variables
                self.sess = tf.Session()
                self.sess.run(tf.global_variables_initializer())

                # Save dictionary
                if not os.path.isdir(self.model_ckpt_dir):
                    os.mkdir(self.model_ckpt_dir)

                with open(os.path.join(self.model_ckpt_dir, 'dictionary'), 'wb') as fp:
                    dictionary = (self.encoder_int_to_vocab, self.encoder_vocab_to_int, self.decoder_int_to_vocab, self.decoder_vocab_to_int)
                    pkl.dump(dictionary, fp)

                with open(os.path.join(self.model_ckpt_dir, 'hparams'), 'wb') as fp:
                    pkl.dump(self.hyparams, fp)

        else:
            # Pre-trained model has loaded
            print('Load pre-trained model')
            self.load(load_model_path)

            # Create seqs
            self.encode_seqs, self.decode_seqs = self._parse_seq(encode_file_path, decode_file_path, self.encoder_vocab_to_int, self.decoder_vocab_to_int, n_buckets=self.hyparams.n_buckets)

            with self.graph.as_default():
                encoder_input = self.graph.get_tensor_by_name('inputs:0')
                encoder_input_seq_lengths = self.graph.get_tensor_by_name('source_lens:0')
                decoder_target = self.graph.get_tensor_by_name('targets:0')
                decoder_target_seq_lengths = self.graph.get_tensor_by_name('target_lens:0')
                keep_prob = self.graph.get_tensor_by_name('dropout:0')
                decoder_output = self.graph.get_tensor_by_name('optimization/training_output:0')
                lr = self.graph.get_tensor_by_name('optimization/learning_rate:0')
                train_op = tf.get_collection("optimization")[0]
                cost = tf.get_collection("optimization")[1]
                global_step = tf.get_collection("optimization")[2]


        encode_pad_id = self.encoder_vocab_to_int['<PAD>']
        decode_pad_id = self.decoder_vocab_to_int['<PAD>']

        # Validate set reserve
        n_valid_data = int(len(self.encode_seqs) * self.hyparams.valid_portion) // self.hyparams.train_batch_size * self.hyparams.train_batch_size
        valid_idx_set = set(np.random.choice(np.arange(len(self.encode_seqs)), n_valid_data, replace=False))
        
        valid_encode_seqs = [seq for i, seq in enumerate(self.encode_seqs) if i in valid_idx_set]
        valid_decode_seqs = [seq for i, seq in enumerate(self.decode_seqs) if i in valid_idx_set]
        valid_batch_generator = self._padding_batch(valid_encode_seqs, valid_decode_seqs, self.hyparams.train_batch_size, encode_pad_id, decode_pad_id, forever=True)

        train_encode_seqs = [seq for i, seq in enumerate(self.encode_seqs) if i not in valid_idx_set]
        train_decode_seqs = [seq for i, seq in enumerate(self.decode_seqs) if i not in valid_idx_set]

        n_batch = len(train_encode_seqs) // self.hyparams.train_batch_size

        # Train the model
        with self.graph.as_default():
            # Create a saver
            saver = tf.train.Saver(max_to_keep=1)

            # Learning rate generator
            lr_gen = self.lr_schedule(self.hyparams.learning_rate, self.hyparams.decay_start_at, self.hyparams.decay_every, self.hyparams.decay_rate)

            if DEBUG:
                summary_writer = tf.summary.FileWriter(os.path.join(self.model_ckpt_dir, 'tensorboard'))
                summary_writer.add_graph(self.sess.graph)
                summary_ops = tf.summary.merge_all()

            g_step = self.sess.run(global_step) % n_batch
            # Pass trained batch
            batch_generator = self._padding_batch(train_encode_seqs, train_decode_seqs, self.hyparams.train_batch_size, encode_pad_id, decode_pad_id)
            for _ in range(g_step):
                _ = next(batch_generator)

            # Start training
            start_epoch = 1 + g_step // n_batch
            for epoch_i in range(start_epoch, self.hyparams.epoch+1):
                for cur_batch_pack in batch_generator:
                    inputs, inputs_lens, targets, targets_lens = cur_batch_pack

                    lr_val = next(lr_gen)
                    _, train_loss, g_step = self.sess.run(
                            [train_op, cost, global_step],
                            feed_dict={
                                encoder_input:inputs,
                                encoder_input_seq_lengths:inputs_lens,
                                decoder_target:targets,
                                decoder_target_seq_lengths:targets_lens,
                                keep_prob: self.hyparams.keep_prob,
                                lr: lr_val
                                }
                            )
                    print("\r{}/{} ".format(g_step % n_batch, n_batch), end='', flush=True)

                    if g_step % self.hyparams.report_every == 0:
                        valid_batch_pack = next(valid_batch_generator)
                        valid_inputs, valid_inputs_lens, valid_targets, valid_targets_lens = valid_batch_pack

                        val_loss, prediction_lists = self.sess.run([cost, decoder_output], feed_dict={
                            encoder_input:valid_inputs,
                            encoder_input_seq_lengths:valid_inputs_lens,
                            decoder_target:valid_targets,
                            decoder_target_seq_lengths:valid_targets_lens,
                            keep_prob: 1.0
                            })

                        bleu_score = self._bleu(prediction_lists, valid_targets, self.hyparams.bleu_max_order, self.hyparams.bleu_smooth)
                        print("E:{}/{} B:{} - train loss: {}\tvalid loss: {}\tvalid bleu: {}\tlr: {}".format(epoch_i, self.hyparams.epoch, g_step, train_loss, val_loss, bleu_score, lr_val))

                    if g_step % self.hyparams.show_every == 0:
                        # Vivid example
                        print('*********')
                        idx = np.random.choice(np.arange(len(prediction_lists)))
                        prediction_str = ' '.join([self.decoder_int_to_vocab.get(n, '<UNK>') for n in prediction_lists[idx]])
                        input_str = ' '.join([self.encoder_int_to_vocab.get(n, '<UNK>') for n in valid_inputs[idx]])
                        target_str = ' '.join([self.decoder_int_to_vocab.get(n, '<UNK>') for n in valid_targets[idx]])
                        print('INPUT: ', input_str)
                        print('PRED: ', prediction_str)
                        print('EXPECT: ', target_str)
                        print('*********')
                    
                    if g_step % self.hyparams.save_every == 0:
                        saver.save(self.sess, self.model_ckpt_path, write_meta_graph=True)

                    if DEBUG and g_step % self.hyparams.summary_every == 0:
                        summary_info = self.sess.run(summary_ops, feed_dict={
                            encoder_input:inputs,
                            encoder_input_seq_lengths:inputs_lens,
                            decoder_target:targets,
                            decoder_target_seq_lengths:targets_lens,
                            keep_prob: self.hyparams.keep_prob
                            })
                        summary_writer.add_summary(summary_info, self.sess.run(global_step))

                    if g_step > self.hyparams.max_global_step:
                        break
                if g_step > self.hyparams.max_global_step:
                    break
                
                # Get a new batch-generator
                batch_generator = self._padding_batch(train_encode_seqs, train_decode_seqs, self.hyparams.train_batch_size, encode_pad_id, decode_pad_id)


    def predict(self, encode_str):
        '''
        Predict the sequence transformation. Make sure you load the model before using this method.
        @encode_str: str, the input string that we give to model for transforming. 
        @return: str, the answer string of the model
        '''
        if not hasattr(self, 'sess'):
            self.load(self.model_ckpt_dir)

        encoder_unk_id = self.encoder_vocab_to_int['<UNK>']
        decoder_pad_id = self.decoder_vocab_to_int['<PAD>']
        decoder_eos_id = self.decoder_vocab_to_int['<EOS>']

        # Parse encode_str
        encode_str = self.tp.process_str(encode_str)
        inputs = [[self.encoder_vocab_to_int.get(word, encoder_unk_id) for word in encode_str.split()]]
        inputs_lens = [len(line) for line in inputs]

        with self.graph.as_default():
            encoder_input = self.graph.get_tensor_by_name('inputs:0')
            encoder_input_seq_lengths = self.graph.get_tensor_by_name('source_lens:0')
            decoder_target_seq_lengths = self.graph.get_tensor_by_name('target_lens:0')
            keep_prob = self.graph.get_tensor_by_name('dropout:0')
            prediction = self.graph.get_tensor_by_name('optimization/predictions:0')

            predict_list = self.sess.run(
                    prediction, 
                    feed_dict={
                        encoder_input:inputs*self.hyparams.infer_batch_size,
                        encoder_input_seq_lengths:inputs_lens*self.hyparams.infer_batch_size,
                        keep_prob: 1.0
                        }
                    )

        return ' '.join([self.decoder_int_to_vocab.get(i, '') for i in predict_list[0]])# if i!=decoder_pad_id and i!=decoder_eos_id])
        # print(predict_list)


    def load(self, path):
        '''
        Load existed model. Error will be raised if not success.
        @path: str, the path of existed model
        @return: None
        '''
        if not os.path.isdir(path):
            raise ValueError('{} is not valid path, your model is probably untrained'.format(path))

        self._id = os.path.basename(path)
        self.model_ckpt_dir = path
        self.model_ckpt_path = os.path.join(path, 'checkpoint.ckpt')
        
        if not os.path.isfile(os.path.join(path, 'checkpoint')):
            raise ValueError('There is no checkpoint file in {}, your model has not finished training'.format(path))

        if not os.path.isfile(os.path.join(path, 'dictionary')):
            raise ValueError('There is no dictionary file in {}'.format(path))

        if not os.path.isfile(os.path.join(path, 'hparams')):
            raise ValueError('There is no hparams file in {}'.format(path))

        with open(os.path.join(path, 'dictionary'), 'rb') as fp:
            self.encoder_int_to_vocab, self.encoder_vocab_to_int, self.decoder_int_to_vocab, self.decoder_vocab_to_int = pkl.load(fp)

        with open(os.path.join(path, 'hparams'), 'rb') as fp:
            loaded_hyparams = pkl.load(fp)
            self.hyparams = self._merge(loaded_hyparams, self.init_hyparams)

        self.graph = tf.Graph()
        with self.graph.as_default():
            self.sess = tf.Session()
            loader = tf.train.import_meta_graph(self.model_ckpt_path+'.meta')
            loader.restore(self.sess, tf.train.latest_checkpoint(path))


class TextProcessor:
    def __init__(self):
        '''
        A simple processor for text dataset
        '''
        self.proc_fn_list = [self.proc1, self.proc2, self.proc3, self.proc4, self.proc5, self.proc6, self.proc7, self.proc8]

    # pickle cann't dump lambda function in py3, so...
    def proc1(self, x):
        return re.sub('\(.*?\)', '', x)
    def proc2(self, x):
        return re.sub('\[.*?\]', '', x)
    def proc3(self, x):
        return re.sub('\{.*?\}', '', x)
    def proc4(self, x):
        return re.sub('\w+\.{,1}\w\.+', lambda y:y.group().replace('.',''), x)
    def proc5(self, x):
        return re.sub('[:\-\/\\*&$#@\^]+|\.{2,}', ' ', x)
    def proc6(self, x):
        return re.sub('[,.!?;]+', lambda y:' '+y.group()+' ', x)
    def proc7(self, x):
        return re.sub('[\=\<\>\"\`\(\)\[\]\{\}]+', '', x)
    def proc8(self, x):
        return re.sub('[ ^]\'[ $]', '', x)

    def read(self, file_path):
        '''
        Load file content into processor instance.
        @file_path: str, the path of file you want to process
        @return: self, return self instance for chaining behaviour
        '''
        if not os.path.isfile(file_path):
            raise ValueError('{} is not valid file path'.format(file_path))
        else:
            self.file_path = file_path

        with open(file_path, 'r') as fp:
            self.lines = fp.readlines()

        return self

    def append(self, proc_fn):
        '''
        Append subprocessing method to default method stack.
        @proc_fn: function, function with a string as input and a string as output
        @return: None
        '''
        self.proc_fn_list.append(proc_fn)

    def process(self, proc_fn_list=[], inplace=False, overwrite=False):
        '''
        Apply process methods on each line of the file
        @proc_fn_list: list, default to empty list, if specified, default processing method stack will be overwrited.
        @inplace: bool, if True, processed content will write back to <file_path> you read in.
        @overwrite: bool, if False, the original file will be saved as <file_path>.origin and processed content will be saved at <file_path>. If True, the origin version will not be saved.
        @return: list or string, if inplace==True, the <file_path> will be returned, if inplace==False, a list of processed sentences will be returned.
        '''
        if len(proc_fn_list) == 0:
            proc_fn_list = self.proc_fn_list

        new_lines = []
        n_lines = len(self.lines)
        for i, line in enumerate(self.lines):
            if i % 1000 == 0 or i == n_lines - 1: 
                print('\rProcessing {}/{}'.format(i+1, n_lines), end='', flush=True)
            for fn in proc_fn_list:
                line = fn(line)
            line += '\n' if len(line)==0 or line[-1] != '\n' else ''
            new_lines.append(line)

        print()
        new_content = ''.join(new_lines)

        if not inplace:
            return new_lines

        else:
            filedir = os.path.dirname(self.file_path)
            filename = os.path.basename(self.file_path)
            if not overwrite:
                os.rename(self.file_path, os.path.join(filedir, filename+'.origin'))
            with open(self.file_path, 'w') as fp:
                fp.write(new_content)
            return self.file_path

    def process_str(self, string, proc_fn_list=[]):
        '''
        Process a single string and return the processed string
        @string: str, input string
        @proc_fn_list: list, default to empty list and use default processing methods. If specified, only your methods will be used.
        '''
        if len(proc_fn_list) == 0:
            proc_fn_list = self.proc_fn_list

        for fn in proc_fn_list:
            string = fn(string)

        return string



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
            description='Build a sequence to sequence bot')
    parser.add_argument(
            '-e', '--enc', type=str, help='The path of encode file, which contains questions')
    parser.add_argument(
            '-d', '--dec', type=str, help='The path of decode file, which contains answers')
    parser.add_argument(
            '--id', type=str, help='The id of the model, if not set the id will be a unique sequence of numbers')
    parser.add_argument(
            '--model', help='The path of pre-trained model, if not set, then new model will be trained')
    parser.add_argument(
            '--loop', action='store_true', help='Contitue predict answers until pressing ctrl-c')
    parser.add_argument(
            '--input', help='Input one string and get prediction return')

    # Advanced arguments
    parser.add_argument(
            '--embedding_dim', type=int, help='Size of embedding layer size of both encoder and decoder, default to 512')
    parser.add_argument(
            '--rnn_layer_size', type=int, help='Single rnn layer size of both encoder and decoder, default to 1024')
    parser.add_argument(
            '--n_rnn_layers', type=int, help='Number of rnn layers of both encoder and decoder, default to 3')
    parser.add_argument(
            '--beam_width', type=int, help='The width of beam search, default to 3')
    parser.add_argument(
            '--keep_prob', type=float, help='Output(dropout) keep probability for each rnn node, default to 0.8')
    parser.add_argument(
            '--valid_portion', type=float, help='Percentage of data used as validation set, default to 0.05')
    parser.add_argument(
            '--train_batch_size', type=int, help='Batch size while training, default to 32')
    parser.add_argument(
            '--infer_batch_size', type=int, help='Batch size while infering, default to 1')
    parser.add_argument(
            '--max_gradient_norm', type=float, help='Clip value for global gradients, default to 5.0')
    parser.add_argument(
            '--epoch', type=int, help='Number of training epoch, default to 10')
    parser.add_argument(
            '--max_global_step', type=int, help='Maximum training steps, default to infinity, which means training for {epoch} times')
    parser.add_argument(
            '--learning_rate', type=float, help='The learning rate, default to 0.001')
    parser.add_argument(
            '--decay_start_at', type=int, help='The learning rate begin to decay after training {this} number of steps, default to 8000')
    parser.add_argument(
            '--decay_every', type=int, help='For every {this} steps, learning_rate=learning_rate * decay_rate, default to 1000')
    parser.add_argument(
            '--decay_rate', type=float, help='The decay rate of learning rate, default to 0.5')
    parser.add_argument(
            '--n_buckets', type=int, help='Seperate training sequence into {this} buckets, training sequences in same bucket have similar length, default to 50')
    parser.add_argument(
            '--vocab_remain_rate', type=float, help='Choose a vocab size that can cover {this} percentage of total words, default to 0.97')
    parser.add_argument(
            '--input_seq_min_len', type=int, help='Minimum length of sequence that used for training, default to 0')
    parser.add_argument(
            '--input_seq_max_len', type=int, help='Maximum length of sequence that used for training, default to infinity')
    parser.add_argument(
            '--bleu_max_order', type=int, help='the max order for n-gram, default to 4')
    parser.add_argument(
            '--bleu_smooth', type=int, help='whether use smoothed bleu score. If False, 0.0 would be more frequent in bleu score. default to 1')
    parser.add_argument(
            '--report_every', type=int, help='Report metrics on validation set for every {this} steps, default to 50')
    parser.add_argument(
            '--show_every', type=int, help='Show an translation example for every {this} steps, default to 200')
    parser.add_argument(
            '--summary_every', type=int, help='Save summary info for every {this} steps, only used when DEBUG=1, default to 50')
    parser.add_argument(
            '--save_every', type=int, help='Save the checkpoint for every {this} steps, default to 500')


    args = parser.parse_args()

    model_args = vars(args).copy()
    _ = [model_args.pop(key) for key in ['enc', 'dec', 'id', 'model', 'loop', 'input']]
    model_args = {k:v for k, v in model_args.items() if v != None}

    model = Seq2seq(**model_args)

    if args.id != None:
        model.set_id(args.id)

    if args.model != None:
        model_path = args.model
        model.load(model_path)

        if args.loop:
            while True:
                input_str = input('> ')
                print('>> {}'.format(model.predict(input_str)))

        elif args.input != None:
            print('> {}'.format(args.input))
            print('>> {}'.format(model.predict(args.input)))

    # (Re)train the model
    if args.enc != None and args.dec != None:
        tp = TextProcessor()
        if not os.path.isfile(args.enc+'.origin'):
            tp.read(args.enc).process(inplace=True)
        if not os.path.isfile(args.dec+'.origin'):
            tp.read(args.dec).process(inplace=True)

        if args.model != None:
            model._train(args.enc, args.dec, args.model)
        else:
            model.train(args.enc, args.dec)

        print('Model is saved at {}'.format(model.model_ckpt_dir))
    elif not all([args.enc, args.dec]) and any([args.enc, args.dec]):
        raise ValueError('You should specify both enc and dec file path')

