-- Version 7 (01/11/2026): the microSD card was retired and the backup target is
-- now any external storage ("armazenamento"), not only HDs.
-- Push topics: 'cartao' (card problems) gives way to 'lote' (a batch is waiting
-- for an external storage). Everyone who had 'cartao' gets 'lote' instead.

UPDATE push_subscriptions
   SET topics = (SELECT json_group_array(value) FROM json_each(push_subscriptions.topics)
                  WHERE value <> 'cartao')
 WHERE EXISTS (SELECT 1 FROM json_each(push_subscriptions.topics) WHERE value = 'cartao');

UPDATE push_subscriptions
   SET topics = json_insert(topics, '$[#]', 'lote')
 WHERE NOT EXISTS (SELECT 1 FROM json_each(push_subscriptions.topics) WHERE value = 'lote')
   AND json_array_length(topics) > 0;
