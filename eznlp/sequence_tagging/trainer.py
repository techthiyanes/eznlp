# -*- coding: utf-8 -*-
import torch

from ..metrics import precision_recall_f1_report
from ..training.trainer import Trainer
from .dataset import SequenceTaggingDataset


class SequenceTaggingTrainer(Trainer):
    def __init__(self, model: torch.nn.Module, **kwargs):
        super().__init__(model, **kwargs)
        
        
    def forward_batch(self, batch):
        losses, hidden = self.model(batch, return_hidden=True)
        loss = losses.mean()
        
        batch_tags_pred = self.model.decode(batch, hidden)
        batch_chunks_pred = [self.model.decoder.translator.tags2chunks(tags) for tags in batch_tags_pred]
        
        batch_chunks_gold = [tags_obj.chunks for tags_obj in batch.tags_objs]
        return loss, batch_chunks_gold, batch_chunks_pred
        
    
    def evaluate(self, y_gold: list, y_pred: list):
        # Use micro-F1, according to https://www.clips.uantwerpen.be/conll2000/chunking/output.html
        scores, ave_scores = precision_recall_f1_report(y_gold, y_pred)
        return ave_scores['micro']['f1']
    
    
    def predict_tags(self, dataset: SequenceTaggingDataset, batch_size=32):
        dataloader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=dataset.collate)
        
        self.model.eval()
        set_tags = []
        with torch.no_grad():
            for batch in dataloader:
                batch.to(self.device)
                set_tags.extend(self.model.decode(batch))
        return set_tags
    
    
    def predict_chunks(self, dataset: SequenceTaggingDataset, batch_size=32):
        set_tags = self.predict_tags(dataset, batch_size=batch_size)
        set_chunks = [self.model.decoder.translator.tags2chunks(tags) for tags in set_tags]
        return set_chunks
    
    