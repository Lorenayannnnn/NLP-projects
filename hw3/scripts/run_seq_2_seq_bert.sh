caffeinate -s python train.py \
    --in_data_fn=lang_to_sem_data.json \
    --outputs_dir=outputs/experiments/s2s_bert/ \
    --model_output_filename=s2s_w_bert_decoder_model.ckpt \
    --batch_size=128 \
    --num_epochs=1 \
    --val_every=1 \
    --force_cpu \
    --use_bert=True \
    --teacher_forcing\
    --encoder_decoder_attention