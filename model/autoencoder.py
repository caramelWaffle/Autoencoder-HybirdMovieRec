import torch
import numpy as np
import pandas as pd
import pickle
import multiprocessing
import os
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader


def get_cv_idxs(n, cv_idx=0, val_pct=0.2, seed=0):
    np.random.seed(seed)
    n_val = int(val_pct * n)
    idx_start = cv_idx * n_val
    idxs = np.random.permutation(n)
    return idxs[idx_start:idx_start + n_val]


def split_by_idx(idxs, *a):
    mask = np.zeros(len(a[0]), dtype=bool)
    mask[np.array(idxs)] = True
    return [(o[mask], o[~mask]) for o in a]


class AutoEncoder(object):

    def __init__(self, data, validation_perc=0.2, lr=0.001,
                 intermediate_size=1000, encoded_size=100, is_enable_bath_norm=True):

        # create training dataloader and validation tensor
        torch.manual_seed(0)
        self.data = data
        self.val_idxs = get_cv_idxs(n=data.shape[0], val_pct=validation_perc)
        [(self.val, self.train)] = split_by_idx(self.val_idxs, data)
        self.dataset = AETrainingData(self.train)
        self.dataloader = DataLoader(self.dataset, batch_size=64, shuffle=True, num_workers=0)
        self.val = torch.from_numpy(self.val).type(torch.FloatTensor).cuda()

        # instantiate the encoder and decoder nets
        size = data.shape[1]
        self.encoder = Encoder(size, intermediate_size, encoded_size, is_enable_bath_norm).cuda()
        self.decoder = Decoder(size, intermediate_size, encoded_size, is_enable_bath_norm).cuda()

        # instantiate the optimizers
        self.encoder_optimizer = optim.Adam(
            self.encoder.parameters(), lr=lr, weight_decay=1e-8)
        self.decoder_optimizer = optim.Adam(
            self.decoder.parameters(), lr=lr, weight_decay=1e-8)

        # instantiate the loss criterion
        self.criterion = nn.MSELoss(reduction='mean')

        self.train_losses = []
        self.val_losses = []

    def train_step(self, input_tensor, target_tensor):
        # clear the gradients in the optimizers
        self.encoder_optimizer.zero_grad()
        self.decoder_optimizer.zero_grad()

        # Forward pass through
        encoded_representation = self.encoder(input_tensor)
        reconstruction = self.decoder(encoded_representation)

        # Compute the loss
        loss = self.criterion(reconstruction, target_tensor)

        # Compute the gradients
        loss.backward()

        # Step the optimizers to update the model weights
        self.encoder_optimizer.step()
        self.decoder_optimizer.step()

        # Return the loss value to track training progress
        return loss.item()

    def reset(self, train=True):
        # due to dropout the network behaves differently in training and
        # evaluation modes
        if train:
            self.encoder.train(); self.decoder.train()
        else:
            self.encoder.eval(); self.decoder.eval()

    def get_val_loss(self, input_tensor, target_tensor):
        self.reset(train=False)
        encoded = self.encoder(input_tensor)
        decoded = self.decoder(encoded)
        loss = self.criterion(decoded, target_tensor)
        return loss.item()

    def train_loop(self, epochs, print_every_n_batches=100):

        # Cycle through epochs
        for epoch in range(epochs):
            print(f'Epoch {epoch + 1}/{epochs}')

            # Cycle through batches
            for i, batch in enumerate(self.dataloader):

                self.reset(train=True)

                input_tensor = batch['input'].cuda()
                target_tensor = batch['target'].cuda()

                loss = self.train_step(input_tensor, target_tensor)

                if i % print_every_n_batches == 0 and i != 0:
                    val_loss = self.get_val_loss(self.val, self.val)
                    print(f'train loss: {round(loss, 8)} | ' +
                          f'validation loss: {round(val_loss, 8)})')
                    self.train_losses.append(loss)
                    self.val_losses.append(val_loss)

    def get_encoded_representations(self):
        to_encode = torch.from_numpy(self.data).type(
            torch.FloatTensor).cuda()
        self.reset(train=False)
        # encodings = self.encoder(to_encode).cpu().data.numpy()
        encodings = self.encoder.forward(self.data)
        return encodings

    def save_encoder(self):

        torch.save(self.encoder.state_dict(), 'checkpoint/encoder_checkpoint.pt')

    def save_decoder(self):
        torch.save(self.decoder.state_dict(), 'checkpoint/decoder_checkpoint.pt')

    def load_encoder(self):
        self.encoder.load_state_dict(torch.load('checkpoint/encoder_checkpoint.pt'), strict=False)

    def load_decoder(self):
        self.encoder.load_state_dict(torch.load('checkpoint/decoder_checkpoint.pt'), strict=False)


class AETrainingData(Dataset):
    """
    Format the training dataset to be input into the auto encoder.
    Takes in dataframe and converts it to a PyTorch Tensor
    """

    def __init__(self, x_train):
        self.x = x_train

    def __len__(self):
        return len(self.x)

    def __getitem__(self, idx):
        """
        Returns a example from the data set as a pytorch tensor.
        """
        # Get example/target pair at idx as numpy arrays
        x, y = self.x[idx], self.x[idx]

        # Convert to torch tensor
        x = torch.from_numpy(x).type(torch.FloatTensor)
        y = torch.from_numpy(y).type(torch.FloatTensor)

        # Return pair
        return {'input': x, 'target': y}


class Encoder(nn.Module):
    def __init__(self, input_size, intermediate_size, encoding_size, is_enable_bath_norm):
        super().__init__()
        if is_enable_bath_norm:
            self.encoder = nn.Sequential(
                nn.Linear(input_size, intermediate_size),
                nn.BatchNorm1d(intermediate_size),
                nn.ReLU(True),
                nn.Dropout(0.2),
                nn.Linear(intermediate_size, encoding_size),
                nn.BatchNorm1d(encoding_size),
                nn.ReLU(True),
                nn.Dropout(0.2))
        else:
            self.encoder = nn.Sequential(
                nn.Linear(input_size, intermediate_size),
                nn.ReLU(True),
                nn.Linear(intermediate_size, encoding_size),
                nn.ReLU(True),
            )

    def forward(self, x):
        x = self.encoder(x)
        return x


class Decoder(nn.Module):
    def __init__(self, output_size, intermediate_size, encoding_size, is_enable_bath_norm):
        super().__init__()
        if is_enable_bath_norm:
            self.decoder = nn.Sequential(
                nn.Linear(encoding_size, intermediate_size),
                nn.BatchNorm1d(intermediate_size),
                nn.ReLU(True),
                nn.Dropout(0.2),
                nn.Linear(intermediate_size, output_size),
                nn.BatchNorm1d(output_size),
                nn.Sigmoid())
        else:
            self.decoder = nn.Sequential(
                nn.Linear(encoding_size, intermediate_size),
                nn.ReLU(True),
                nn.Linear(intermediate_size, output_size),
                nn.Sigmoid())

    def forward(self, x):
        x = self.decoder(x)
        return x
