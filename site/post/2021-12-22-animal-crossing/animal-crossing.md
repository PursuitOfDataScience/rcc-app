URL: https://youzhi.netlify.app/post/2021-12-22-animal-crossing/animal-crossing/
Title: Animal Crossing Data Visualization & Structural Topic Modeling
Date: 2021-12-22
---

This blog post analyzes the game Animal Crossing datasets from [TidyTuesday](https://github.com/rfordatascience/tidytuesday/tree/master/data/2020/2020-05-05). I do not play games, but this analysis would give me some opportunity to understand what this game is. Also, this is my first time using the `stm` package, which is an R package helping build up structural topic modeling.

```r
library(tidyverse)
library(lubridate)
library(tidytext)
library(patchwork)
library(scales)
library(stm)
library(broom)
library(lubridate)
theme_set(theme_bw())
```

```r
critic <- read_tsv('https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-05-05/critic.tsv')
user_reviews <- read_tsv('https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-05-05/user_reviews.tsv')
items <- read_csv('https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-05-05/items.csv')
villagers <- read_csv('https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-05-05/villagers.csv')
```

### Critic grades {#critic-grades}

```r
critic %>%
 mutate(grade = cut(grade, c(70, 80, 90, 100), include.lowest = T)) %>%
 mutate(grade = paste("grade:", grade),
 grade = fct_reorder(grade, parse_number(grade))) %>%
 unnest_tokens(word, text) %>%
 anti_join(stop_words) %>%
 filter(!word %in% c("animal", "crossing")) %>%
 count(grade, word, sort = T) %>%
 group_by(grade) %>%
 slice_max(n, n = 5) %>%
 ungroup() %>%
 mutate(word = fct_reorder(word, n, sum)) %>%
 ggplot(aes(n, word, fill = grade)) +
 geom_col() +
 labs(x = "word count",
 y = NULL,
 fill = NULL,
 title = "Top 5 words from each grade interval")
```

### User reviews {#user-reviews}

```r
user_reviews %>%
 unnest_tokens(word, text) %>%
 anti_join(stop_words) %>%
 count(grade, word, sort = T) %>%
 filter(!word %in% c("game", "animal", "crossing", "island", "games")) %>%
 group_by(grade) %>%
 slice_max(n, n = 10) %>%
 ggplot(aes(factor(grade), n, color = word)) +
 geom_point() +
 geom_text(aes(label = word), hjust = 1, vjust = 1, check_overlap = T) +
 theme(legend.position = "none") +
 labs(x = "user grade",
 y = "word count",
 title = "Top 10 words from every user grade")
```

The following section Structural Topic Modeling is inspired by David Robinson's [code](https://github.com/dgrtwo/data-screencasts/blob/master/animal-crossing.Rmd).

### Structural Topic Modeling {#structural-topic-modeling}

```r
user_review_words <- user_reviews %>%
 unnest_tokens(word, text) %>%
 anti_join(stop_words, by = "word") %>%
 count(user_name, date, grade, word)

user_review_words
```

```
## # A tibble: 88,346 x 5
## user_name date grade word n
## <chr> <date> <dbl> <chr> <int>
## 1 000anon2759 2020-04-01 0 anti 1
## 2 000anon2759 2020-04-01 0 console 1
## 3 000anon2759 2020-04-01 0 consumer 1
## 4 000anon2759 2020-04-01 0 disappointing 1
## 5 000anon2759 2020-04-01 0 greedy 1
## 6 000anon2759 2020-04-01 0 island 1
## 7 000anon2759 2020-04-01 0 practice 1
## 8 000anon2759 2020-04-01 0 unfair 1
## 9 000PLAYER000 2020-03-20 10 playing 1
## 10 000PLAYER000 2020-03-20 10 stop 1
## # ... with 88,336 more rows
```

```r
review_matrix <- user_review_words %>%
 group_by(word) %>%
 filter(n() > 50) %>%
 cast_sparse(user_name, word, n)
```

Constructing a 8-topic model, and two visualizations can be made here. One is \(\beta\), which stands for the probability of each term related to each topic. The other one is \(\gamma\), the probability of each document (in this case each user review) to each of eight topic set here.

```r
topic_model_8 <- stm(review_matrix, K = 8)
```

```
## Beginning Spectral Initialization
## Calculating the gram matrix...
## Finding anchor words...
## ........
## Recovering initialization...
## ..
## Initialization complete.
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 1 (approx. per word bound = -4.884)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 2 (approx. per word bound = -4.806, relative change = 1.586e-02)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 3 (approx. per word bound = -4.779, relative change = 5.691e-03)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 4 (approx. per word bound = -4.765, relative change = 3.035e-03)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 5 (approx. per word bound = -4.756, relative change = 1.726e-03)
## Topic 1: de, la, juego, es, en
## Topic 2: game, switch, save, island, multiple
## Topic 3: game, people, island, 0, reviews
## Topic 4: review, game, expand, items, island
## Topic 5: game, player, island, play, progress
## Topic 6: game, island, switch, play, nintendo
## Topic 7: game, time, games, series, fun
## Topic 8: crossing, animal, horizons, game, el
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 6 (approx. per word bound = -4.751, relative change = 1.091e-03)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 7 (approx. per word bound = -4.748, relative change = 7.186e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 8 (approx. per word bound = -4.745, relative change = 4.766e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 9 (approx. per word bound = -4.744, relative change = 3.303e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 10 (approx. per word bound = -4.743, relative change = 2.401e-04)
## Topic 1: de, la, juego, es, en
## Topic 2: game, multiple, switch, save, system
## Topic 3: game, people, island, 10, reviews
## Topic 4: review, game, expand, items, crafting
## Topic 5: player, game, island, progress, play
## Topic 6: game, island, switch, play, nintendo
## Topic 7: game, time, games, fun, series
## Topic 8: crossing, animal, horizons, el, game
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 11 (approx. per word bound = -4.742, relative change = 1.878e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 12 (approx. per word bound = -4.741, relative change = 1.522e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 13 (approx. per word bound = -4.740, relative change = 1.369e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 14 (approx. per word bound = -4.740, relative change = 1.295e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 15 (approx. per word bound = -4.739, relative change = 1.204e-04)
## Topic 1: de, la, juego, es, en
## Topic 2: game, multiple, switch, save, islands
## Topic 3: game, people, 10, island, reviews
## Topic 4: review, expand, game, items, crafting
## Topic 5: player, game, island, progress, players
## Topic 6: game, island, switch, play, nintendo
## Topic 7: game, time, games, fun, played
## Topic 8: crossing, animal, horizons, el, game
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 16 (approx. per word bound = -4.739, relative change = 1.041e-04)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 17 (approx. per word bound = -4.738, relative change = 8.828e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 18 (approx. per word bound = -4.738, relative change = 7.519e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 19 (approx. per word bound = -4.738, relative change = 6.299e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 20 (approx. per word bound = -4.737, relative change = 5.162e-05)
## Topic 1: de, la, es, juego, en
## Topic 2: game, multiple, islands, save, switch
## Topic 3: game, people, 10, island, bad
## Topic 4: review, expand, game, items, island
## Topic 5: player, game, island, progress, players
## Topic 6: game, island, switch, play, nintendo
## Topic 7: game, time, games, fun, played
## Topic 8: crossing, animal, horizons, el, fan
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 21 (approx. per word bound = -4.737, relative change = 4.109e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 22 (approx. per word bound = -4.737, relative change = 3.236e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 23 (approx. per word bound = -4.737, relative change = 2.560e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 24 (approx. per word bound = -4.737, relative change = 2.023e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 25 (approx. per word bound = -4.737, relative change = 1.604e-05)
## Topic 1: de, la, es, juego, en
## Topic 2: multiple, game, islands, save, switch
## Topic 3: game, people, 10, island, bad
## Topic 4: review, expand, island, game, items
## Topic 5: player, game, island, progress, players
## Topic 6: game, island, switch, play, nintendo
## Topic 7: game, time, fun, games, played
## Topic 8: crossing, animal, horizons, series, el
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 26 (approx. per word bound = -4.737, relative change = 1.308e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Completing Iteration 27 (approx. per word bound = -4.737, relative change = 1.109e-05)
## ......................................................................................................
## Completed E-Step (0 seconds).
## Completed M-Step.
## Model Converged
```

```r
topic_model_8 %>%
 tidy(matrix = "beta") %>%
 mutate(topic = paste("Topic:", topic)) %>%
 group_by(topic) %>%
 slice_max(beta, n = 10) %>%
 ungroup() %>%
 mutate(term = reorder_within(term, beta, topic)) %>%
 ggplot(aes(beta, term, fill = topic)) +
 geom_col(show.legend = F) +
 scale_y_reordered() +
 facet_wrap(~topic, scales = "free_y")
```

```r
topic_model_gamma <- topic_model_8 %>%
 tidy(matrix = "gamma") %>%
 mutate(user_name = rownames(review_matrix)[document],
 topic = paste("Topic:", topic)) %>%
 inner_join(user_reviews, by = "user_name")

topic_model_gamma %>%
 group_by(topic, week = floor_date(date, unit = "week", week_start = 1)) %>%
 summarize(avg_gamma = mean(gamma)) %>%
 ungroup() %>%
 ggplot(aes(week, avg_gamma, color = topic)) +
 geom_line(size = 1) +
 labs(x = NULL,
 y = "average gamma",
 color = NULL,
 title = "Weekly average gamma values based on topics",
 subtitle = "Gamma values refer to the probablity of each review belonging to each topic")
```

### Villagers {#villagers}

```r
month_day <- tibble(month = seq(1:12), month_abb = month.abb)

villagers_date <- villagers %>%
 separate(birthday, into = c("month", "day"), sep = "-", convert = T) %>%
 left_join(month_day, by = "month") %>%
 mutate(month_abb = fct_reorder(month_abb, month))

villagers_date %>%
 ggplot(aes(month_abb)) +
 geom_histogram(stat = "count") +
 labs(x = "birthday month",
 title = "Villager birthday month distribution")
```

Birthday months are more or less equally distributed. Maybe this is an intertional game design!

```r
villagers_date %>%
 count(month_abb, personality, sort = T) %>%
 group_by(month_abb) %>%
 slice_max(n, n = 5) %>%
 ungroup() %>%
 ggplot(aes(month_abb, personality, fill = n)) +
 geom_tile() +
 theme(panel.grid = element_blank()) +
 scale_fill_gradient2(high = "green",
 low = "red",
 mid = "pink",
 midpoint = 6) +
 labs(x = "",
 fill = "count",
 title = "Does birth month affect personality?")
```

### Gender and species {#gender-and-species}

```r
villagers %>%
 count(gender, species, sort = T) %>%
 mutate(species = fct_reorder(species, n, sum)) %>%
 ggplot(aes(n, species, fill = gender)) +
 geom_col() +
 labs(x = "count",
 fill = NULL,
 title = "All species and their gender")
```

### Item depreciation rate {#item-depreciation-rate}

Depreciation rate is defined as the sell value divides by the buy value.

```r
items %>%
 filter(buy_currency == "bells") %>%
 mutate(deprection_rate = sell_value/buy_value) %>%
 filter(deprection_rate < 0.35) %>%
 ggplot(aes(deprection_rate, category)) +
 geom_boxplot()
```

The deprection rate is rather consistent among all categories. We can verify it from the weighted categorical depreciation rate as follows.

Weighted categorical depreciation rate

```r
items %>%
 filter(buy_currency == "bells") %>%
 group_by(category) %>%
 summarize(buy_value_sum = sum(buy_value, na.rm = T),
 sell_value_sum = sum(sell_value, na.rm = T)) %>%
 ungroup() %>%
 filter(buy_value_sum > 0) %>%
 mutate(category_depreciation_rate = sell_value_sum/buy_value_sum,
 category = fct_reorder(category, category_depreciation_rate)) %>%
 ggplot(aes(category_depreciation_rate, category)) +
 geom_col() +
 labs(x = "categorical depreciation rate",
 title = "Categorical depreciation rates") +
 scale_x_continuous(labels = scales::percent)
```

Sell price and buy price

```r
items %>%
 ggplot(aes(buy_value, sell_value, color = category)) +
 geom_point() +
 geom_text(aes(label = name), hjust = 1, vjust = 1, check_overlap = T) +
 scale_x_log10(labels = dollar) +
 scale_y_log10(labels = dollar) +
 coord_fixed() +
 labs(x = "purchase price",
 y = "sell price",
 title = "Sell price V.S. purchase price")
```

### Global buy and sell values {#global-buy-and-sell-values}

```r
p1 <- items %>%
 filter(buy_currency == "bells") %>%
 mutate(category = fct_reorder(category, buy_value, median, na.rm = T)) %>%
 ggplot(aes(buy_value, category, fill = category)) +
 geom_boxplot(show.legend = F) +
 scale_x_log10(label = dollar) +
 labs(x = "buy value",
 title = "Categorical buy value")
p2 <- items %>%
 filter(sell_currency == "bells") %>%
 mutate(category = fct_reorder(category, sell_value, median, na.rm = T)) %>%
 ggplot(aes(sell_value, category, fill = category)) +
 geom_boxplot(show.legend = F) +
 scale_x_log10(label = dollar) +
 labs(x = "sell value",
 title = "Categorical sell value")

p1 / p2
```
