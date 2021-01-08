# -*- coding: utf-8 -*-
from functools import cached_property
import torch
from torch.nn.utils.rnn import pad_sequence

from ..data import Batch
from ..data.dataset import unpad_seqs
from ..decoder import DecoderConfig, Decoder
from .transition import ChunksTagsTranslator
from .crf import CRF


class SequenceTaggingDecoderConfig(DecoderConfig):
    def __init__(self, **kwargs):
        self.arch = kwargs.pop('arch', 'CRF')
        if self.arch.lower() not in ('softmax', 'crf'):
            raise ValueError(f"Invalid decoder architecture {self.arch}")
            
        self.scheme = kwargs.pop('scheme', 'BIOES')
        self.idx2tag = kwargs.pop('idx2tag', None)
        super().__init__(**kwargs)
        
    def __repr__(self):
        repr_attr_dict = {key: self.__dict__[key] for key in ['arch', 'in_dim', 'scheme', 'in_drop_rates']}
        return self._repr_non_config_attrs(repr_attr_dict)
        
    @cached_property
    def translator(self):
        return ChunksTagsTranslator(scheme=self.scheme)
        
    @cached_property
    def tag2idx(self):
        """
        The first access to this property should be after `idx2tag` properly set. 
        """
        return {t: i for i, t in enumerate(self.idx2tag)}
        
    @property
    def voc_dim(self):
        return len(self.tag2idx)
        
    @property
    def pad_idx(self):
        return self.tag2idx['<pad>']
        
    def instantiate(self):
        if self.arch.lower() == 'softmax':
            return SequenceTaggingSoftMaxDecoder(self)
        elif self.arch.lower() == 'crf':
            return SequenceTaggingCRFDecoder(self)
        
        
        
class SequenceTaggingDecoder(Decoder):
    def __init__(self, config: SequenceTaggingDecoderConfig):
        super().__init__(config)
        self.scheme = config.scheme
        self.translator = config.translator
        self.idx2tag = config.idx2tag
        self.tag2idx = config.tag2idx
        
        
        
class SequenceTaggingSoftMaxDecoder(SequenceTaggingDecoder):
    def __init__(self, config: SequenceTaggingDecoderConfig):
        super().__init__(config)
        self.criterion = torch.nn.CrossEntropyLoss(ignore_index=config.pad_idx, reduction='sum')
        
    def forward(self, batch: Batch, full_hidden: torch.Tensor):
        # logits: (batch, step, tag_dim)
        logits = self.hid2logit(self.dropout(full_hidden))
        
        losses = [self.criterion(lg[:slen], tags_obj.tag_ids) for lg, tags_obj, slen in zip(logits, batch.tags_objs, batch.seq_lens.cpu().tolist())]
        # `torch.stack`: Concatenates sequence of tensors along a new dimension. 
        losses = torch.stack(losses, dim=0)
        return losses
    
    
    def decode(self, batch: Batch, full_hidden: torch.Tensor):
        # logits: (batch, step, tag_dim)
        logits = self.hid2logit(full_hidden)
        
        best_paths = logits.argmax(dim=-1)
        batch_tag_ids = unpad_seqs(best_paths, batch.seq_lens)
        return [[self.idx2tag[i] for i in tag_ids] for tag_ids in batch_tag_ids]
    
    
    
class SequenceTaggingCRFDecoder(SequenceTaggingDecoder):
    def __init__(self, config: SequenceTaggingDecoderConfig):
        super().__init__(config)
        self.crf = CRF(tag_dim=config.voc_dim, pad_idx=config.pad_idx, batch_first=True)
        
        
    def forward(self, batch: Batch, full_hidden: torch.Tensor):
        # logits: (batch, step, tag_dim)
        logits = self.hid2logit(self.dropout(full_hidden))
        
        batch_tag_ids = pad_sequence([tags_obj.tag_ids for tags_obj in batch.tags_objs], batch_first=True, padding_value=self.crf.pad_idx)
        losses = self.crf(logits, batch_tag_ids, mask=batch.tok_mask)
        return losses
    
    
    def decode(self, batch: Batch, full_hidden: torch.Tensor):
        # logits: (batch, step, tag_dim)
        logits = self.hid2logit(full_hidden)
        
        # List of List of predicted-tag-ids
        batch_tag_ids = self.crf.decode(logits, mask=batch.tok_mask)
        return [[self.idx2tag[i] for i in tag_ids] for tag_ids in batch_tag_ids]
    
    