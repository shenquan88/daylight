/* Daylight · 向阳 — front end. No framework, no build step.
   User text always goes through textContent / createTextNode, never innerHTML. */

(function () {
  "use strict";

  var refs = {};
  var state = null;

  function $(id) { return document.getElementById(id); }

  function toast(message, isError) {
    var el = refs.toast;
    el.textContent = message;
    el.classList.toggle("is-error", !!isError);
    el.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { el.hidden = true; }, 3200);
  }

  function api(path, options) {
    return fetch(path, options || {}).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (err) { data = null; }
        }
        if (!res.ok) {
          var msg = (data && data.error) || ("请求失败（" + res.status + "）");
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  function postJson(path, payload) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    });
  }

  var WEEKDAYS = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];

  function prettyDate(day) {
    if (!day) return "";
    var d = new Date(day + "T00:00:00");
    if (isNaN(d.getTime())) return day;
    return d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日 · " +
      WEEKDAYS[d.getDay()];
  }

  function prettyTime(iso) {
    if (!iso) return "";
    var m = /T(\d{2}):(\d{2})/.exec(iso);
    return m ? m[1] + ":" + m[2] : iso;
  }

  /* ------------------------------------------------------------ plants */

  var PLANT_SVG = {
    seed:
      '<svg viewBox="0 0 100 110" role="img" aria-label="种子">' +
      '<ellipse cx="50" cy="98" rx="30" ry="8" fill="#F6E3CF"/>' +
      '<ellipse cx="50" cy="90" rx="7" ry="9" fill="#C98F5A"/>' +
      '<path d="M50 84c0-6 3-10 7-12" stroke="#8FC894" stroke-width="3" fill="none" stroke-linecap="round"/>' +
      '</svg>',
    sprout:
      '<svg viewBox="0 0 100 110" role="img" aria-label="幼苗">' +
      '<ellipse cx="50" cy="98" rx="30" ry="8" fill="#F6E3CF"/>' +
      '<path d="M50 95V64" stroke="#6FAE74" stroke-width="4" stroke-linecap="round"/>' +
      '<path d="M50 74c-12 0-18-6-18-14 11 0 18 5 18 14z" fill="#8FC894"/>' +
      '<path d="M50 66c11-1 16-7 16-15-10 0-16 6-16 15z" fill="#A8D6AC"/>' +
      '</svg>',
    leaf:
      '<svg viewBox="0 0 100 110" role="img" aria-label="长叶">' +
      '<ellipse cx="50" cy="98" rx="32" ry="8" fill="#F6E3CF"/>' +
      '<path d="M50 95V44" stroke="#5C9E63" stroke-width="4" stroke-linecap="round"/>' +
      '<path d="M50 78c-14 0-21-7-21-16 13 0 21 6 21 16z" fill="#8FC894"/>' +
      '<path d="M50 70c13-1 19-8 19-17-12 0-19 7-19 17z" fill="#A8D6AC"/>' +
      '<path d="M50 58c-12 0-18-6-18-14 11 0 18 5 18 14z" fill="#7FBF87"/>' +
      '<path d="M50 50c11-1 17-7 17-15-11 0-17 6-17 15z" fill="#9BD1A0"/>' +
      '</svg>',
    bud:
      '<svg viewBox="0 0 100 110" role="img" aria-label="花苞">' +
      '<ellipse cx="50" cy="98" rx="32" ry="8" fill="#F6E3CF"/>' +
      '<path d="M50 95V44" stroke="#5C9E63" stroke-width="4" stroke-linecap="round"/>' +
      '<path d="M50 78c-14 0-21-7-21-16 13 0 21 6 21 16z" fill="#8FC894"/>' +
      '<path d="M50 70c13-1 19-8 19-17-12 0-19 7-19 17z" fill="#A8D6AC"/>' +
      '<ellipse cx="50" cy="34" rx="10" ry="13" fill="#FFC08A"/>' +
      '<path d="M50 21v-6" stroke="#5C9E63" stroke-width="3" stroke-linecap="round"/>' +
      '</svg>',
    bloom:
      '<svg viewBox="0 0 100 110" role="img" aria-label="开花">' +
      '<ellipse cx="50" cy="98" rx="32" ry="8" fill="#F6E3CF"/>' +
      '<path d="M50 95V44" stroke="#5C9E63" stroke-width="4" stroke-linecap="round"/>' +
      '<path d="M50 78c-14 0-21-7-21-16 13 0 21 6 21 16z" fill="#8FC894"/>' +
      '<path d="M50 70c13-1 19-8 19-17-12 0-19 7-19 17z" fill="#A8D6AC"/>' +
      '<g fill="#F9822F">' +
      '<circle cx="50" cy="18" r="7"/><circle cx="62" cy="26" r="7"/>' +
      '<circle cx="62" cy="40" r="7"/><circle cx="50" cy="48" r="7"/>' +
      '<circle cx="38" cy="40" r="7"/><circle cx="38" cy="26" r="7"/>' +
      '</g>' +
      '<circle cx="50" cy="33" r="8" fill="#FFD08A"/>' +
      '</svg>'
  };

  /* ------------------------------------------------------------ render */

  function renderMode(data) {
    var badge = refs.modeBadge;
    if (data.mode === "connector") {
      badge.textContent = "连接器模式";
      badge.className = "badge badge-connector";
      badge.title = "经验卡由 Sprite connector 模型生成，内容仍来自你的真实记录";
    } else {
      badge.textContent = "本地模式";
      badge.className = "badge badge-local";
      badge.title = "使用本地模板生成经验卡，不联网";
    }
  }

  function renderProgress(data) {
    var p = data.progress || { done: 0, total: 0, percent: 0 };
    refs.ring.style.setProperty("--p", String(p.percent));
    refs.percent.textContent = p.percent + "%";
    refs.bar.style.width = p.percent + "%";

    var line;
    if (!p.total) {
      line = "今天还没开始，先从一个小目标起步。";
    } else if (p.done === 0) {
      line = "已经有 " + p.total + " 个小目标在等你，先挑最容易的那个。";
    } else if (p.done < p.total) {
      line = "已完成 " + p.done + " 个，还有 " + (p.total - p.done) + " 个在推进。";
    } else {
      line = "今天的 " + p.total + " 个目标都完成了，收工。";
    }
    refs.progressLine.textContent = line;

    refs.streakLine.textContent = data.streak
      ? "连续记录第 " + data.streak + " 天"
      : "今天写下第一条记录，连续从 1 开始";
  }

  function renderGoals(data) {
    var list = refs.goalList;
    list.textContent = "";
    (data.goals || []).forEach(function (goal) {
      var li = document.createElement("li");
      li.className = "goal" + (goal.done ? " is-done" : "");

      var check = document.createElement("button");
      check.type = "button";
      check.className = "goal-check";
      check.textContent = goal.done ? "✓" : "";
      check.setAttribute("aria-label", goal.done ? "已完成" : "标记「" + goal.text + "」完成");
      if (goal.done) {
        check.disabled = true;
      } else {
        check.addEventListener("click", function () { completeGoal(goal.id, check); });
      }

      var main = document.createElement("div");
      main.className = "goal-main";
      var text = document.createElement("p");
      text.className = "goal-text";
      text.textContent = goal.text;
      main.appendChild(text);
      if (goal.next_step) {
        var step = document.createElement("p");
        step.className = "goal-step";
        step.textContent = "下一步：" + goal.next_step;
        main.appendChild(step);
      }

      var stamp = document.createElement("span");
      stamp.className = "goal-time";
      stamp.textContent = goal.done
        ? "完成于 " + prettyTime(goal.done_at)
        : "加入于 " + prettyTime(goal.created_at);

      li.appendChild(check);
      li.appendChild(main);
      li.appendChild(stamp);
      list.appendChild(li);
    });

    var hasGoals = (data.goals || []).length > 0;
    refs.goalEmpty.hidden = hasGoals;

    var steps = refs.nextSteps;
    steps.textContent = "";
    var openGoals = (data.goals || []).filter(function (g) { return !g.done; });
    if (!openGoals.length) {
      var none = document.createElement("li");
      none.textContent = hasGoals
        ? "今天的目标都完成了。留一点空，或者再加一个小的。"
        : "先加一个目标，这里就会出现第一个能马上做的动作。";
      steps.appendChild(none);
    } else {
      openGoals.forEach(function (g) {
        if (!g.next_step) return;
        var li = document.createElement("li");
        li.textContent = g.next_step + "（对应：" + g.text + "）";
        steps.appendChild(li);
      });
    }
  }

  function renderTimeline(data) {
    var list = refs.timeline;
    list.textContent = "";
    var items = (data.checkins || []).slice().reverse();
    items.forEach(function (c) {
      var li = document.createElement("li");
      var time = document.createElement("span");
      time.className = "tl-time";
      time.textContent = prettyTime(c.created_at);
      var did = document.createElement("p");
      did.className = "tl-did";
      did.textContent = c.did;
      li.appendChild(time);
      li.appendChild(did);
      if (c.learned) {
        var learned = document.createElement("p");
        learned.className = "tl-learned";
        learned.textContent = "学到：" + c.learned;
        li.appendChild(learned);
      }
      list.appendChild(li);
    });
    refs.timelineEmpty.hidden = items.length > 0;
    list.hidden = items.length === 0;
  }

  function renderCard(data) {
    var cards = data.cards || [];
    if (!cards.length) {
      refs.cardBody.hidden = true;
      refs.cardBody.textContent = "";
      return;
    }
    refs.cardBody.hidden = false;
    refs.cardBody.textContent = cards[0].body;
  }

  function renderGarden(data) {
    var garden = refs.garden;
    garden.textContent = "";
    var days = data.garden || [];
    days.forEach(function (entry) {
      var card = document.createElement("div");
      card.className = "plant";
      card.tabIndex = 0;
      card.setAttribute("role", "button");
      var label = "打开 " + entry.day + " 的记录";
      card.setAttribute("aria-label", label);

      var art = document.createElement("div");
      art.innerHTML = PLANT_SVG[entry.stage] || PLANT_SVG.seed;
      card.appendChild(art);

      var day = document.createElement("p");
      day.className = "plant-day";
      day.textContent = entry.day.slice(5);
      card.appendChild(day);

      var meta = document.createElement("p");
      meta.className = "plant-meta";
      meta.textContent = entry.activity + " 个动作";
      card.appendChild(meta);

      card.addEventListener("click", function () { openPlant(entry); });
      card.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openPlant(entry);
        }
      });
      garden.appendChild(card);
    });
    refs.gardenEmpty.hidden = days.length > 0;
  }

  function render(data) {
    state = data;
    renderMode(data);
    refs.todayBadge.textContent = prettyDate(data.today);
    refs.todayDate.textContent = prettyDate(data.today);
    renderProgress(data);
    renderGoals(data);
    renderTimeline(data);
    renderCard(data);
    renderGarden(data);
  }

  /* ------------------------------------------------------------ actions */

  function load() {
    return api("/api/state").then(render).catch(function (err) {
      toast(err.message || "读取失败，请刷新页面", true);
    });
  }

  function completeGoal(id, button) {
    if (button) button.disabled = true;
    postJson("/api/goals/" + id + "/complete", {})
      .then(function (res) {
        render(res.state);
        toast("完成一个，记下了。");
      })
      .catch(function (err) {
        if (button) button.disabled = false;
        toast(err.message, true);
      });
  }

  function submitGoal(ev) {
    ev.preventDefault();
    var input = refs.goalInput;
    var text = input.value.trim();
    if (!text) {
      toast("先写一句话，哪怕很短", true);
      input.focus();
      return;
    }
    postJson("/api/goals", { text: text })
      .then(function (res) {
        render(res.state);
        input.value = "";
        toast("已加入今天。下一步：" + ((res.goal && res.goal.next_step) || "先做 10 分钟"));
      })
      .catch(function (err) { toast(err.message, true); });
  }

  function submitCheckin(ev) {
    ev.preventDefault();
    var did = refs.didInput.value.trim();
    if (!did) {
      toast("写一句「我做了什么」", true);
      refs.didInput.focus();
      return;
    }
    postJson("/api/checkins", { did: did, learned: refs.learnedInput.value.trim() })
      .then(function (res) {
        render(res.state);
        refs.didInput.value = "";
        refs.learnedInput.value = "";
        toast("记下了，今天又多了一步。");
      })
      .catch(function (err) { toast(err.message, true); });
  }

  function reflect() {
    refs.reflectBtn.disabled = true;
    refs.reflectBtn.textContent = "生成中…";
    postJson("/api/reflect", {})
      .then(function (res) {
        render(res.state);
        toast(res.card.mode === "connector" ? "经验卡已生成（连接器模式）" : "经验卡已生成（本地模式）");
      })
      .catch(function (err) { toast(err.message, true); })
      .then(function () {
        refs.reflectBtn.disabled = false;
        refs.reflectBtn.textContent = "生成今日经验卡";
      });
  }

  function refreshHealth() {
    return api("/api/health").then(function (h) {
      refs.factDir.textContent = h.data_dir;
      refs.factDb.textContent = h.db_path;
      refs.factSize.textContent = h.db_bytes + " 字节";
      refs.factLastWrite.textContent = h.last_write || "还没有写入";
      refs.factCounts.textContent = "目标 " + h.counts.goals + " · 记录 " +
        h.counts.checkins + " · 经验卡 " + h.counts.cards;
      refs.factNow.textContent = h.server_time;
      refs.factConnector.textContent = h.connector && h.connector.configured
        ? ("连接器已配置：" + h.connector.model)
        : "本地模式（未配置 connector，全部离线可用）";
    }).catch(function (err) {
      toast(err.message || "健康检查失败", true);
    });
  }

  /* ------------------------------------------------------------ plant modal */

  function block(title, items, asParagraphs) {
    if (!items.length) return null;
    var wrap = document.createElement("div");
    wrap.className = "detail-block";
    var h = document.createElement("h4");
    h.textContent = title;
    wrap.appendChild(h);
    if (asParagraphs) {
      items.forEach(function (text) {
        var pre = document.createElement("pre");
        pre.textContent = text;
        wrap.appendChild(pre);
      });
      return wrap;
    }
    var ul = document.createElement("ul");
    items.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    return wrap;
  }

  function openPlant(entry) {
    refs.plantTitle.textContent = prettyDate(entry.day) + " · " + entry.activity + " 个动作";
    var body = refs.plantBody;
    body.textContent = "";

    var goals = (entry.goals || []).map(function (g) {
      return (g.done ? "✓ 已完成：" : "· 进行中：") + g.text;
    });
    var checkins = (entry.checkins || []).map(function (c) {
      return c.did + (c.learned ? "（学到：" + c.learned + "）" : "");
    });
    var cards = (entry.cards || []).map(function (c) { return c.body; });

    [block("那天的小目标", goals), block("那天的行动", checkins),
     block("那天的经验卡", cards, true)].forEach(function (node) {
      if (node) body.appendChild(node);
    });

    if (!goals.length && !checkins.length) {
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "这天只有一株刚开始的苗，还没有文字记录。";
      body.appendChild(empty);
    }

    refs.plantModal.hidden = false;
    refs.plantClose.focus();
  }

  function closePlant() {
    refs.plantModal.hidden = true;
  }

  /* ------------------------------------------------------------ wiring */

  function switchView(name) {
    document.querySelectorAll(".tab").forEach(function (tab) {
      var active = tab.getAttribute("data-view") === name;
      tab.classList.toggle("is-active", active);
      if (active) { tab.setAttribute("aria-current", "page"); }
      else { tab.removeAttribute("aria-current"); }
    });
    document.querySelectorAll(".view").forEach(function (view) {
      var active = view.id === "view-" + name;
      view.classList.toggle("is-active", active);
      view.hidden = !active;
    });
    if (name === "about") refreshHealth();
  }

  function init() {
    refs = {
      modeBadge: $("mode-badge"), todayBadge: $("today-badge"), todayDate: $("today-date"),
      ring: $("progress-ring"), percent: $("progress-percent"),
      progressLine: $("progress-line"), bar: $("bar-fill"), streakLine: $("streak-line"),
      goalList: $("goal-list"), goalEmpty: $("goal-empty"), nextSteps: $("next-steps"),
      goalForm: $("goal-form"), goalInput: $("goal-input"),
      checkinForm: $("checkin-form"), didInput: $("did-input"), learnedInput: $("learned-input"),
      timeline: $("timeline"), timelineEmpty: $("timeline-empty"),
      cardBody: $("card-body"), reflectBtn: $("reflect-btn"),
      garden: $("garden"), gardenEmpty: $("garden-empty"),
      factDir: $("fact-dir"), factDb: $("fact-db"), factSize: $("fact-size"),
      factLastWrite: $("fact-lastwrite"), factCounts: $("fact-counts"),
      factNow: $("fact-now"), factConnector: $("fact-connector"),
      toast: $("toast"), plantModal: $("plant-modal"), plantTitle: $("plant-title"),
      plantBody: $("plant-body"), plantClose: $("plant-close"), healthBtn: $("health-btn")
    };

    document.querySelectorAll(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () { switchView(tab.getAttribute("data-view")); });
    });

    refs.goalForm.addEventListener("submit", submitGoal);
    refs.checkinForm.addEventListener("submit", submitCheckin);
    refs.reflectBtn.addEventListener("click", reflect);
    refs.healthBtn.addEventListener("click", refreshHealth);
    refs.plantClose.addEventListener("click", closePlant);
    refs.plantModal.addEventListener("click", function (ev) {
      if (ev.target === refs.plantModal) closePlant();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !refs.plantModal.hidden) closePlant();
    });

    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
