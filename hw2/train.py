import argparse
import os

import tqdm
import torch
from sklearn.metrics import accuracy_score
from torch.utils.data import TensorDataset, DataLoader

from eval_utils import downstream_validation
import utils
import data_utils
from model import CBOWModel


def setup_dataloader(args, context_window_len):
    """
    return:
        - train_loader: torch.utils.data.Dataloader
        - val_loader: torch.utils.data.Dataloader
    """

    # read in training data from books dataset
    sentences = data_utils.process_book_dir(args.data_dir)

    # build one hot maps for input and output
    (
        vocab_to_index,
        index_to_vocab,
        suggested_padding_len,
    ) = data_utils.build_tokenizer_table(sentences, vocab_size=args.vocab_size)

    # create encoded input and output numpy matrices for the entire dataset and then put them into tensors
    encoded_sentences, lens = data_utils.encode_data(
        sentences,
        vocab_to_index,
        suggested_padding_len,
    )

    # ===================================================== #
    # Task: Given the tokenized and encoded text, you need to
    # create inputs to the LM model you want to train.
    # E.g., could be target word in -> context out or
    # context in -> target word out.
    # You can build up that input/output table across all
    # encoded sentences in the dataset!
    # Then, split the data into train set and validation set
    # (you can use utils functions) and create respective
    # dataloaders.
    # ===================================================== #

    # Split all sentences: train and validation
    print("INFO: Start parsing sentences to train and validation dataset")
    train_sentences, val_sentences, train_sentences_lens, val_sentences_lens = utils.create_train_val_splits(
        all_sentences=encoded_sentences, lens=lens)

    pad_token = vocab_to_index['<pad>']

    # CBOW
    train_input, train_labels = utils.get_input_label_data_cbow(train_sentences, context_window_len, pad_token,
                                                                train_sentences_lens)
    val_input, val_labels = utils.get_input_label_data_cbow(val_sentences, context_window_len, pad_token,
                                                            val_sentences_lens)

    train_dataset = TensorDataset(torch.from_numpy(train_input), torch.from_numpy(train_labels))
    val_dataset = TensorDataset(torch.from_numpy(val_input), torch.from_numpy(val_labels))

    train_loader = DataLoader(train_dataset, shuffle=True, batch_size=args.batch_size)
    val_loader = DataLoader(val_dataset, shuffle=False, batch_size=args.batch_size)
    print("INFO: Finished parsing sentences to train and validation dataset")
    return train_loader, val_loader, index_to_vocab


def setup_model(args, n_vocab: int, context_window_len: int):
    """
    return:
        - model: SkipGramModel/CBOWModel
    """
    # ===================================================== #
    # Task: Initialize your CBOW or Skip-Gram model.
    # ===================================================== #
    n_embedding = 100
    model = CBOWModel(n_vocab, n_embedding, context_window_len)
    return model


def setup_optimizer(args, model, device):
    """
    return:
        - criterion: loss_fn
        - optimizer: torch.optim
    """
    # ===================================================== #
    # Task: Initialize the loss function for predictions. 
    # Also initialize your optimizer.
    # ===================================================== #
    # CBOW
    criterion = torch.nn.CrossEntropyLoss().to(device)
    optimizer = torch.optim.Adam(params=model.parameters())
    return criterion, optimizer


def train_epoch(
    args,
    model,
    loader,
    optimizer,
    criterion,
    device,
    training=True,
):
    model.train()
    epoch_loss = 0.0

    # keep track of the model predictions for computing accuracy
    pred_labels = []
    target_labels = []

    # iterate over each batch in the dataloader
    # NOTE: you may have additional outputs from the loader __getitem__, you can modify this
    for (inputs, labels) in tqdm.tqdm(loader):
        # put model inputs to device
        inputs, labels = inputs.to(device).long(), labels.to(device).long()

        # calculate the loss and train accuracy and perform backprop
        # NOTE: feel free to change the parameters to the model forward pass here + outputs
        pred_logits = model(inputs)

        # calculate prediction loss
        loss = criterion(pred_logits.squeeze(), labels)

        # step optimizer and compute gradients during training
        if training:
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        # logging
        epoch_loss += loss.item()

        # compute metrics
        # CBOW
        preds = pred_logits.argmax(-1)
        pred_labels.extend(preds.cpu().numpy())
        target_labels.extend(labels.cpu().numpy())

    acc = accuracy_score(pred_labels, target_labels)
    epoch_loss /= len(loader)

    return epoch_loss, acc


def validate(args, model, loader, optimizer, criterion, device):
    # set model to eval mode
    model.eval()

    # don't compute gradients
    with torch.no_grad():
        val_loss, val_acc = train_epoch(
            args,
            model,
            loader,
            optimizer,
            criterion,
            device,
            training=False,
        )

    return val_loss, val_acc


def main(args):
    device = utils.get_device(args.force_cpu)

    # load analogies for downstream eval
    external_val_analogies = utils.read_analogies(args.analogies_fn)

    if args.downstream_eval:
        word_vec_file = os.path.join(args.outputs_dir, args.word_vector_fn)
        assert os.path.exists(word_vec_file), "need to train the word vecs first!"
        downstream_validation(word_vec_file, external_val_analogies)
        return

    # get dataloaders
    context_window_len = 2      # context window length
    train_loader, val_loader, index_to_vocab = setup_dataloader(args, context_window_len)
    loaders = {"train": train_loader, "val": val_loader}

    # build model
    # Reserve 4 for 4 special tokens (<pad>...)
    model = setup_model(args, n_vocab=args.vocab_size, context_window_len=context_window_len)
    print(model)

    # get optimizer
    criterion, optimizer = setup_optimizer(args, model, device)

    all_train_acc = []
    all_train_loss = []
    all_val_acc = []
    all_val_loss = []

    for epoch in range(args.num_epochs):
        # train model for a single epoch
        print(f"Epoch {epoch}")
        train_loss, train_acc = train_epoch(
            args,
            model,
            loaders["train"],
            optimizer,
            criterion,
            device,
        )

        print(f"train loss : {train_loss} | train acc: {train_acc}")
        all_train_acc.append(train_acc)
        all_train_loss.append(train_loss)

        if epoch % args.val_every == 0:
            val_loss, val_acc = validate(
                args,
                model,
                loaders["val"],
                optimizer,
                criterion,
                device,
            )
            print(f"val loss : {val_loss} | val acc: {val_acc}")
            all_val_acc.append(val_acc)
            all_val_loss.append(val_loss)

            # ======================= NOTE ======================== #
            # Saving the word vectors to disk and running the eval
            # can be costly when you do it multiple times. You could
            # change this to run only when your training has concluded.
            # However, incremental saving means if something crashes
            # later or you get bored and kill the process you'll still
            # have a word vector file and some results.
            # ===================================================== #

            # # save word vectors
            # word_vec_file = os.path.join(args.outputs_dir, args.word_vector_fn)
            # print("saving word vec to ", word_vec_file)
            # utils.save_word2vec_format(word_vec_file, model, index_to_vocab)
            #
            # # evaluate learned embeddings on a downstream task
            # downstream_validation(word_vec_file, external_val_analogies)

        if epoch != 0 and epoch % args.save_every == 0:
            ckpt_file = os.path.join(args.outputs_dir, "model.ckpt")
            print("saving model to ", ckpt_file)
            torch.save(model, ckpt_file)

    # Output training and validation accuracy and loss graphs
    utils.output_result_figure(args, "output_graphs/training_loss.png", all_train_loss, "Training Loss", False)
    utils.output_result_figure(args, "output_graphs/training_acc.png", all_train_acc, "Training Accuracy", False)
    utils.output_result_figure(args, "output_graphs/validation_loss.png", all_val_loss, "Validation Loss", True)
    utils.output_result_figure(args, "output_graphs/validation_acc.png", all_val_acc, "Validation Accuracy", True)

    # save word vectors
    word_vec_file = os.path.join(args.outputs_dir, args.word_vector_fn)
    print("saving word vec to ", word_vec_file)
    utils.save_word2vec_format(word_vec_file, model, index_to_vocab)

    # evaluate learned embeddings on a downstream task
    downstream_validation(word_vec_file, external_val_analogies)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs_dir", type=str, default="output", help="where to save training outputs")
    parser.add_argument("--data_dir", type=str, help="where the book dataset is stored")
    parser.add_argument(
        "--downstream_eval",
        action="store_true",
        help="run downstream eval on trained word vecs",
    )
    # ======================= NOTE ======================== #
    # If you adjust the vocab_size down below 3000, there 
    # may be analogies in the downstream evaluation that have
    # words that are not in your vocabulary, resulting in
    # automatic (currently) zero score for an ABCD where one
    # of A, B, C, or D is not in the vocab. A visible warning
    # will be generated by the evaluation loop for these examples.
    # ===================================================== #
    parser.add_argument(
        "--vocab_size", type=int, default=3000, help="size of vocabulary"
    )
    parser.add_argument(
        "--batch_size", type=int, default=32, help="size of each batch in loader"
    )
    parser.add_argument("--force_cpu", action="store_true", help="debug mode")
    parser.add_argument(
        "--analogies_fn", type=str, help="filepath to the analogies json file"
    )
    parser.add_argument(
        "--word_vector_fn", type=str, help="filepath to store the learned word vectors",
        default='learned_word_vectors.txt'
    )
    parser.add_argument(
        "--num_epochs", default=30, type=int, help="number of training epochs"
    )
    parser.add_argument(
        "--val_every",
        default=5,
        type=int,
        help="number of epochs between every eval loop",
    )
    parser.add_argument(
        "--save_every",
        default=5,
        type=int,
        help="number of epochs between saving model checkpoint",
    )
    # ===================================================== #
    # Task (optional): Add any additional command line
    # parameters you may need here
    # ===================================================== #

    args = parser.parse_args()
    main(args)