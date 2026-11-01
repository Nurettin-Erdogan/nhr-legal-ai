-- Bir soru ve ona üretilen cevap aynı transaction içinde yazılır. NOW() bir
-- transaction boyunca sabit olduğu için iki mesaj aynı created_at değerini
-- alıyor ve sohbet sırası rastgele UUID karşılaştırmasına kalıyordu.
-- clock_timestamp() transaction içinde ilerlediğinden sıralama belirli olur.
BEGIN;

ALTER TABLE messages
  ALTER COLUMN created_at SET DEFAULT clock_timestamp();

COMMIT;
