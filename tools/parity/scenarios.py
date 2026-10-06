"""Hand-authored basketball plays, encoded separately into V2 and V3 contracts.

These are synthetic facts, not reconstructed historical V2 recordings.
"""
import itertools
import random

HOME,AWAY=1610612761,1610612740
GAME='0021900001'


def e(kind,clock=600,team=HOME,player=1,**kw):
    return dict(kind=kind,clock=str(clock),team=team,player=player,period=1,**kw)


def wrap(events):
    return [e('start',720,0,0)]+events+[e('end',0,0,0)]


def catalog():
    cases=[]
    def add(name,events,**extra):cases.append(dict(name=name,events=wrap(events),**extra))
    add('made_two_then_away_turnover',[e('make'),e('turnover',590,AWAY,11)])
    add('made_three',[e('make',value=3),e('make',590,AWAY,11)])
    add('defensive_rebound',[e('miss'),e('rebound',599,AWAY,11),e('turnover',590,AWAY,11)])
    add('offensive_rebound',[e('miss'),e('rebound',599),e('make',580)])
    add('team_defensive_rebound',[e('miss'),e('rebound',599,AWAY,0),e('make',580,AWAY,11)])
    add('team_offensive_rebound',[e('miss'),e('rebound',599,HOME,0),e('make',580)])
    add('shotclock_placeholder',[e('turnover',subtype='Shot Clock Turnover'),e('rebound',600,AWAY,0),e('make',580,AWAY,11)])
    for n in (2,3):
        for makes in itertools.product((False,True),repeat=n):
            events=[e('foul',600,AWAY,11,subtype='Shooting')]
            for k,made in enumerate(makes,1):
                events.append(e('ft',attempt=k,total=n,made=made))
                if not made and k<n:events.append(e('rebound',600,HOME,0))
            if not makes[-1]:events.append(e('rebound',599,AWAY,11))
            events.append(e('make',580,AWAY,11))
            add(f'ft_{n}_'+''.join('M' if m else 'X' for m in makes),events)
    for made in (False,True):
        add(f'and_one_{made}',[e('make'),e('foul',600,AWAY,11,subtype='Shooting'),e('ft',attempt=1,total=1,made=made)]+([] if made else [e('rebound',599,AWAY,11)])+[e('make',580,AWAY,11)])
    add('substitution_between_fts',[e('foul',600,AWAY,11,subtype='Shooting'),e('ft',attempt=1,total=2,made=True),e('sub',600,HOME,2,incoming=6),e('ft',attempt=2,total=2,made=True),e('make',580,AWAY,11)])
    add('technical_between_regular_fts',[e('foul',600,AWAY,11,subtype='Shooting'),e('ft',attempt=1,total=2,made=True),e('foul',600,AWAY,12,subtype='Technical'),e('ft',600,HOME,2,category='Technical',attempt=1,total=1,made=True),e('ft',attempt=2,total=2,made=True),e('make',580,AWAY,11)])
    add('technical_after_sub_between_regular_fts',[e('foul',600,AWAY,11,subtype='Shooting'),e('ft',attempt=1,total=2,made=True),e('sub',600,HOME,2,incoming=6),e('foul',600,AWAY,12,subtype='Technical'),e('ft',600,HOME,3,category='Technical',attempt=1,total=1,made=True),e('ft',attempt=2,total=2,made=True),e('make',580,AWAY,11)])
    for shooter_team,shooter in ((HOME,1),(AWAY,11)):
        foulteam=AWAY if shooter_team==HOME else HOME
        foulplayer=12 if foulteam==AWAY else 2
        add(f'technical_mid_possession_{shooter_team}',[e('miss',620),e('rebound',619),e('foul',600,foulteam,foulplayer,subtype='Technical'),e('ft',600,shooter_team,shooter,category='Technical',attempt=1,total=1,made=True),e('make',580)])
    for category,foultype in [('Clear Path','Clear Path'),('Flagrant','Flagrant Type 1')]:
        for made in (False,True):
            events=[e('miss',620),e('rebound',619),e('foul',600,AWAY,11,subtype=foultype),e('ft',category=category,attempt=1,total=2,made=True),e('ft',category=category,attempt=2,total=2,made=made)]
            if not made:events.append(e('rebound',600,HOME,0))
            add(f'retained_{category}_{made}',events+[e('make',580)])
    add('away_from_play',[e('foul',600,AWAY,11,subtype='Away From Play'),e('ft',attempt=1,total=1,made=True),e('make',580)])
    add('offensive_foul',[e('foul',600,HOME,1,subtype='Offensive'),e('turnover',subtype='Offensive Foul Turnover'),e('make',580,AWAY,11)])
    add('opening_jump',[e('jump',720,HOME,1,winner_team=AWAY,winner=12,opponent=11),e('make',600,AWAY,11)])
    add('interior_jump_first_possession',[e('miss',620),e('rebound',619),e('jump',600,HOME,1,winner_team=AWAY,winner=12,opponent=11),e('make',580,AWAY,11)])
    add('neutral_timeout',[e('miss',620),e('rebound',619),e('timeout',610,0,0),e('make',580)])
    for clock in ('3','2.8','2.1','2','1.9','0'):
        add('threshold_'+clock,[e('make',clock)])
    for nextmade in (False,True):
        add('future_score_'+str(nextmade),[e('make',2),e('turnover','1.5',AWAY,11),e('make' if nextmade else 'turnover',1)])
    # Source pathologies or legacy-repair cases are kept separate from valid play parity.
    add('ft_before_foul',[e('ft',attempt=1,total=2,made=True),e('foul',600,AWAY,11,subtype='Shooting'),e('ft',attempt=2,total=2,made=True)],category='legacy_repair')
    add('replay_after_period_end',[e('make')],category='legacy_repair')
    cases[-1]['events'].append(e('replay',0,0,0))
    for seed in range(100):
        rng=random.Random(seed)
        events=[]
        offense=HOME
        for p in range(20):
            defense=AWAY if offense==HOME else HOME
            actor=1 if offense==HOME else 11
            defender=11 if offense==HOME else 1
            clock=690-p*30
            kind=rng.choice(['make','miss','turnover','oreb','ft'])
            if kind=='make':events.append(e('make',clock,offense,actor,value=rng.choice([2,3])))
            elif kind=='turnover':events.append(e('turnover',clock,offense,actor))
            elif kind=='miss':events += [e('miss',clock,offense,actor),e('rebound',clock-1,defense,defender)]
            elif kind=='oreb':events += [e('miss',clock,offense,actor),e('rebound',clock-1,offense,actor),e('make',clock-3,offense,actor)]
            else:
                events.append(e('foul',clock,defense,defender,subtype='Shooting'))
                makes=[rng.choice([False,True]),rng.choice([False,True])]
                for k,made in enumerate(makes,1):
                    events.append(e('ft',clock,offense,actor,attempt=k,total=2,made=made))
                    if k==1 and not made:events.append(e('rebound',clock,offense,0))
                if not makes[1]:events.append(e('rebound',clock-1,defense,defender))
            offense=defense
        add(f'generated_{seed:03}',events,expected_groups=21)
    return cases


FOUL_CODES={'Personal':1,'Shooting':2,'Loose Ball':3,'Offensive':4,'Away From Play':6,'Clear Path':9,'Technical':11,'Flagrant Type 1':14}
TURNOVER_CODES={'Bad Pass':1,'Lost Ball':2,'Traveling':4,'Shot Clock Turnover':11,'Offensive Foul Turnover':37}


def encode_v2(events):
    rows=[]
    from decimal import Decimal
    for i,v in enumerate(events,1):
        kind=v['kind'];clock=Decimal(v['clock']);m=int(clock//60);s=clock-60*m
        row=dict(GAME_ID=GAME,EVENTNUM=i,PERIOD=v['period'],PCTIMESTRING=f'{m}:{s:02}',PLAYER1_ID=v['player'],PLAYER1_TEAM_ID=v['team'] or None,PLAYER2_ID=None,PLAYER3_ID=None)
        description=''
        if kind in ('make','miss'):
            row.update(EVENTMSGTYPE=1 if kind=='make' else 2,EVENTMSGACTIONTYPE=1)
            description=('MISS ' if kind=='miss' else '')+f"Player{v['player']} "+('3PT ' if v.get('value')==3 else '')+'Jump Shot'
        elif kind=='ft':
            category=v.get('category','')
            code=16 if category=='Technical' else ({(1,1):10,(1,2):11,(2,2):12,(1,3):13,(2,3):14,(3,3):15}[(v['attempt'],v['total'])] if not category else (17+v['attempt']-1 if category=='Clear Path' else 18+v['attempt']))
            row.update(EVENTMSGTYPE=3,EVENTMSGACTIONTYPE=code)
            description=('' if v['made'] else 'MISS ')+f"Player{v['player']} Free Throw"+(' '+category if category else '')+('' if category=='Technical' else f" {v['attempt']} of {v['total']}")
        elif kind=='foul':row.update(EVENTMSGTYPE=6,EVENTMSGACTIONTYPE=FOUL_CODES[v['subtype']]);description=f"Player{v['player']} Foul"
        elif kind=='turnover':row.update(EVENTMSGTYPE=5,EVENTMSGACTIONTYPE=TURNOVER_CODES[v.get('subtype','Bad Pass')]);description=f"Player{v['player']} Turnover"
        elif kind=='rebound':
            row.update(EVENTMSGTYPE=4,EVENTMSGACTIONTYPE=0);description='REBOUND'
            if not v['player']:row.update(PLAYER1_ID=v['team'],PLAYER1_TEAM_ID=None)
        elif kind=='sub':row.update(EVENTMSGTYPE=8,EVENTMSGACTIONTYPE=0,PLAYER2_ID=v['incoming']);description=f"SUB: Player{v['incoming']} FOR Player{v['player']}"
        elif kind=='jump':row.update(EVENTMSGTYPE=10,EVENTMSGACTIONTYPE=0,PLAYER2_ID=v['opponent'],PLAYER3_ID=v['winner'],PLAYER3_TEAM_ID=v['winner_team']);description=f"Jump Ball Player{v['player']} vs. Player{v['opponent']}: Tip to Player{v['winner']}"
        else:row.update(EVENTMSGTYPE={'start':12,'end':13,'timeout':9,'replay':18}[kind],EVENTMSGACTIONTYPE=0);description=kind
        row['NEUTRALDESCRIPTION']=description
        rows.append(row)
    return rows


def encode_v3(events):
    rows=[]
    from decimal import Decimal
    for i,v in enumerate(events,1):
        clock=Decimal(v['clock']);m=int(clock//60);s=clock-60*m
        row=dict(actionNumber=i,actionId=i,period=v['period'],clock=f'PT{m}M{s}S',personId=v['player'],teamId=v['team'],location='h' if v['team']==HOME else 'v' if v['team']==AWAY else '',shotValue=0,shotResult='',isFieldGoal=0)
        kind=v['kind'];pid=v['player']
        if kind in ('make','miss'):
            row.update(actionType='Made Shot' if kind=='make' else 'Missed Shot',subType='Jump Shot',isFieldGoal=1,shotValue=v.get('value',2),shotResult='Made' if kind=='make' else 'Missed',description=('MISS ' if kind=='miss' else '')+f'Player{pid} Jump Shot')
        elif kind=='ft':
            category=v.get('category','');subtype='Free Throw'+(' '+category if category else '')+('' if category=='Technical' else f" {v['attempt']} of {v['total']}")
            row.update(actionType='Free Throw',subType=subtype,description=('' if v['made'] else 'MISS ')+f'Player{pid} '+subtype+(' (1 PTS)' if v['made'] else ''))
        elif kind=='foul':row.update(actionType='Foul',subType=v['subtype'],description=f'Player{pid} Foul')
        elif kind=='turnover':row.update(actionType='Turnover',subType=v.get('subtype','Bad Pass'),description=f'Player{pid} Turnover')
        elif kind=='rebound':row.update(actionType='Rebound',subType='Unknown',personId=pid or v['team'],description='Rebound')
        elif kind=='sub':row.update(actionType='Substitution',subType='',description=f"SUB: Player{v['incoming']} FOR Player{pid}")
        elif kind=='jump':row.update(actionType='Jump Ball',subType='',description=f"Jump Ball Player{pid} vs. Player{v['opponent']}: Tip to Player{v['winner']}")
        else:row.update(actionType={'start':'period','end':'period','timeout':'Timeout','replay':'Instant Replay'}[kind],subType={'start':'start','end':'end','timeout':'Regular','replay':'Support Ruling'}[kind],description=kind)
        rows.append(row)
    return rows
