import torch
from pytorch_pretrained_bert import BertTokenizer, BertModel, BertForMaskedLM


class EmbeddingUtil:
    sentence = ""
    model = "word2vec"

    def __init__(self, sentence, model):
        self.sentence = sentence
        self.model = model

    def getEmbedding(self):
        if self.model == 'bert':
            return getBertEmbedding(self.sentence)


def getBertEmbedding(sentence):
    # Load pre-trained model tokenizer (vocabulary)
    tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')
    marked_text = "[CLS] " + sentence + " [SEP]"
    tokenized_text = tokenizer.tokenize(marked_text)

    indexed_tokens = tokenizer.convert_tokens_to_ids(tokenized_text)
    segments_ids = [1] * len(tokenized_text)

    tokens_tensor = torch.tensor([indexed_tokens])
    segments_tensors = torch.tensor([segments_ids])

    model = BertModel.from_pretrained('bert-base-uncased')
    model.eval()

    with torch.no_grad():
        encoded_layers, _ = model(tokens_tensor, segments_tensors)

    layer_i = 0
    batch_i = 0
    token_i = 0

    print("Number of hidden units:", len(encoded_layers[layer_i][batch_i][token_i]))

    token_embeddings = []

    for token_i in range(len(tokenized_text)):

        hidden_layers = []

        for layer_i in range(len(encoded_layers)):
            vec = encoded_layers[layer_i][batch_i][token_i]
            hidden_layers.append(vec)

        token_embeddings.append(hidden_layers)

    sentence_embedding = torch.mean(encoded_layers[11], 1)
    return sentence_embedding.numpy()