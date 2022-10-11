import json
import gensim
import numpy
import tqdm
import numpy as np
import torch
import pandas as pd
import matplotlib.pyplot as plt
import data_utils
import os


def read_analogies(analogies_fn):
    with open(analogies_fn, "r") as f:
        pairs = json.load(f)
    return pairs


def save_word2vec_format(fname, model, i2v):
    print("Saving word vectors to file...")  # DEBUG
    with gensim.utils.open(fname, "wb") as fout:
        fout.write(
            gensim.utils.to_utf8("%d %d\n" % (model.n_vocab, model.n_embedding))
        )
        # store in sorted order: most frequent words at the top
        for index in tqdm.tqdm(range(len(i2v))):
            word = i2v[index]
            row = model.embedding_layer.weight.data[index]
            fout.write(
                gensim.utils.to_utf8(
                    "%s %s\n" % (word, " ".join("%f" % val for val in row))
                )
            )


def get_token(sentence: list, index: int, pad_token: int):
    """
    get token at input index of the sentence
    """
    return pad_token if (index < 0 or index >= len(sentence)) else sentence[index]


def create_train_val_splits(all_sentences: list, prop_train=0.7):
    """
    Split all input sentences to train and validation
    Reference: code snippet from coding activity 3
    """
    train_sentences = []
    val_sentences = []
    train_idxs = np.random.choice(list(range(len(all_sentences))), size=int(len(all_sentences) * prop_train + 0.5),
                                  replace=False)
    train_sentences.extend([all_sentences[idx] for idx in range(len(all_sentences)) if idx in train_idxs])
    val_sentences.extend([all_sentences[idx] for idx in range(len(all_sentences)) if idx not in train_idxs])
    return train_sentences, val_sentences


def get_input_label_data_skip_gram(sentences: list, context_window_len: int, pad_token: int, n_vocab: int):
    """
    Parse all sentences and get input and labels (skip_gram)
    token -> context word within the input context window length
    """
    context_list = []
    token_list = []

    for sentence in sentences:
        for (i, token) in enumerate(sentence):
            if token == 0:
                break
            token_list.append(token)
            context = [0] * n_vocab
            bound = int(context_window_len / 2)

            for index in range(i - bound, i + bound + 1):
                if index != i:
                    context[get_token(sentence, index, pad_token)] = 1
            context_list.append(context)

    return numpy.array(token_list), numpy.array(context_list)


def get_input_label_data_cbow(sentences: list, context_window_len: int, pad_token: int, lens):
    """
    Parse all sentences and get input and labels (skip_gram)
    context -> token
    """
    context_list = []
    tokens = []
    bound = int(context_window_len / 2)

    for (sentence_index, sentence) in enumerate(sentences):
        # 1. Start from 1st token
        # for (token_index, token) in enumerate(sentence):
        #     if token_index >= lens[sentence_index][0]:
        #         break
        #     tokens.append(token)
        #
        #     context = []
        #     for bound_index in range(token_index - bound, token_index + bound + 1):
        #         if bound_index != token_index:
        #             context.append(get_token(sentence, bound_index, pad_token))
        #     context_list.append(context)

        # 2. Start from token with a valid context window
        for i in range(bound, len(sentence) - bound):
            if i >= lens[sentence_index][0]:
                break
            tokens.append(sentence[i])
            context = []
            for index in range(i - bound, i + bound + 1):
                if index != i:
                    context.append(get_token(sentence, index, pad_token))
            context_list.append(context)

    return numpy.array(context_list), numpy.array(tokens)


def get_train_val_dataset():
    train_df = pd.read_pickle("train.pkl")
    val_df = pd.read_pickle("val.pkl")

    # Read in data from local pickle file
    x_train = train_df["input_data"].values.tolist()
    y_train = train_df["labels"].values.tolist()
    x_val = val_df["input_data"].values.tolist()
    y_val = val_df["labels"].values.tolist()

    return x_train, y_train, x_val, y_val


def get_device(force_cpu, status=True):
    # Reference: from hw1
    if not force_cpu and torch.cuda.is_available():
        device = torch.device("cuda")
        if status:
            print("Using CUDA")
    else:
        device = torch.device("cpu")
        if status:
            print("Using CPU")
    return device


# TODO
def parse_skipgram_preds(prediction, context_window_len: int):
    index_list = [np.argpartition(indexes.detach().numpy(), -context_window_len)[-context_window_len::] for indexes in prediction]
    parsed_preds = []
    for i, a in enumerate(prediction):
        result = np.zeros(len(a))
        for index in index_list[i]:
            result[index] = 1
        parsed_preds.append(result)

    return torch.tensor(numpy.array(parsed_preds))
    # index_list = np.array([np.argpartition(indexes.detach().numpy(), -context_window_len)[-context_window_len::] for
    #               indexes in prediction])
    # index_list.sort()
    # return index_list


def output_result_figure(args, output_file_name: str, y_axis_data: list, graph_title: str, is_val: bool):
    x_axis_data = [i for i in range(1, args.num_epochs + 1, args.val_every)] if is_val else [i for i in range(1, args.num_epochs + 1)]

    figure, ax = plt.subplots()
    ax.plot(x_axis_data, y_axis_data)
    ax.set_title(graph_title)
    ax.set_xlabel("Num of epochs")
    ax.set_ylim(bottom=0)

    figure.show()

    figure.savefig(output_file_name)


def save_index_to_vocab(arr: list):
    with open('output/index_to_vocab.txt', 'w') as convert_file:
        convert_file.write(json.dumps(arr))


def load_index_to_vocab():
    with open('output/index_to_vocab.txt') as f:
        data = f.read()
    index_to_vocab = json.loads(data)
    index_to_vocab = {int(k): v for k, v in index_to_vocab.items()}

    return index_to_vocab
